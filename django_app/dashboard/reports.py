"""Формирование отчётов: Excel (openpyxl) и CSV."""
import csv
import io

from django.utils import timezone


def _xlsx_style():
    """Общие стили Excel-отчётов."""
    from openpyxl.styles import Font, PatternFill
    return (
        Font(bold=True, color='FFFFFF'),
        PatternFill('solid', fgColor='FF1F4E78'),
        Font(bold=True, size=14),
    )


# ---------------------------------------------------------------------------
# Простои
# ---------------------------------------------------------------------------

def build_downtime_xlsx(meta, events):
    """Отчёт о простоях: события с длительностью, сводка по линиям."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    header_font, header_fill, title_font = _xlsx_style()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Простои'
    ws.append(['Отчёт о простоях'])
    ws['A1'].font = title_font
    ws.append([f'Период: {meta["from_str"]} — {meta["to_str"]}'])
    ws.append([f'Сформирован: {meta["generated_at"]}'])
    ws.append([])
    headers = ['№', 'Линия', 'Цех', 'Продукт', 'Начало простоя', 'Окончание', 'Длительность, мин', 'Статус']
    ws.append(headers)
    for cell in ws[5]:
        cell.font = header_font
        cell.fill = header_fill

    per_line = {}
    for i, e in enumerate(events, start=1):
        ws.append([
            i, e['line_name'], e['shop_name'],
            f"{e['product_code']} — {e['product_name']}",
            timezone.localtime(e['start']).strftime('%d.%m.%Y %H:%M'),
            timezone.localtime(e['end']).strftime('%d.%m.%Y %H:%M'),
            e['minutes'],
            'продолжается' if e['ongoing'] else 'завершён',
        ])
        per_line[e['line_name']] = per_line.get(e['line_name'], 0) + e['minutes']

    total_row = ws.max_row + 1
    ws.cell(row=total_row, column=6, value='ИТОГО, мин:').font = Font(bold=True)
    ws.cell(row=total_row, column=7, value=meta['total_minutes']).font = Font(bold=True)

    for col, w in zip('ABCDEFGH', [5, 42, 26, 40, 18, 18, 16, 14]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'A6'

    if per_line:
        ws2 = wb.create_sheet('Сводка по линиям')
        ws2.append(['Линия', 'Простоев', 'Минут'])
        for cell in ws2[1]:
            cell.font = header_font
            cell.fill = header_fill
        for name, minutes in per_line.items():
            ws2.append([name, sum(1 for e in events if e['line_name'] == name), minutes])
        ws2.column_dimensions['A'].width = 42
        ws2.column_dimensions['B'].width = 10
        ws2.column_dimensions['C'].width = 10

    buf = io.BytesIO()
    wb.save(buf)
    return meta['filename_xlsx'], buf.getvalue()


def build_downtime_csv(meta, events):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';')
    writer.writerow(['Отчёт о простоях'])
    writer.writerow([f'Период: {meta["from_str"]} — {meta["to_str"]}'])
    writer.writerow([f'Сформирован: {meta["generated_at"]}'])
    writer.writerow([])
    writer.writerow(['№', 'Линия', 'Цех', 'Продукт', 'Начало простоя', 'Окончание', 'Длительность, мин', 'Статус'])
    for i, e in enumerate(events, start=1):
        writer.writerow([
            i, e['line_name'], e['shop_name'],
            f"{e['product_code']} — {e['product_name']}",
            timezone.localtime(e['start']).strftime('%d.%m.%Y %H:%M'),
            timezone.localtime(e['end']).strftime('%d.%m.%Y %H:%M'),
            e['minutes'],
            'продолжается' if e['ongoing'] else 'завершён',
        ])
    writer.writerow(['ИТОГО, мин:', '', '', '', '', '', meta['total_minutes'], ''])
    return meta['filename_csv'], buf.getvalue().encode('utf-8-sig')


# ---------------------------------------------------------------------------
# Универсальный экспорт таблиц отчётов (новый движок отчётов)
# ---------------------------------------------------------------------------

def _fmt_cell(v):
    if isinstance(v, (int, float)):
        return v
    return str(v) if v is not None else ''


def _write_report_sheet(ws, meta, table, write_meta=True):
    """Заполняет лист Excel одной таблицей отчёта.

    Формат по образцу: объединённый заголовок отчёта по ширине листа,
    «Сформирован:», шапка отчёта (мета-строки, каждая объединена по ширине),
    строка по центру (если есть), шапка таблицы (жирная, по центру,
    на тёмно-синем фоне; для колонок «Код продукта | Заводской код | …» —
    двухстрочная: «Код:» объединено по 2 колонкам + «Продукта | Заводской»),
    данные, итог, примечание. Ширина колонок — по количеству символов.
    """
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    header_font, header_fill, _ = _xlsx_style()

    def merge_row(row_idx, ncols):
        if ncols > 1:
            ws.merge_cells(start_row=row_idx, start_column=1,
                           end_row=row_idx, end_column=ncols)

    columns = table.get('columns') or []
    ncols = max(len(columns), 1)

    # 1) Заголовок отчёта — объединён по ширине, по центру
    ws.append([meta.get('title', 'Отчёт')])
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal='center', vertical='top', wrap_text=True)
    ws.row_dimensions[1].height = 22.5
    merge_row(1, ncols)

    # 2) Сформирован
    ws.append([f'Сформирован: {meta.get("generated_at", "")}'])
    ws[ws.max_row][0].alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
    merge_row(ws.max_row, ncols)

    # 3) Шапка отчёта (мета-строки)
    if write_meta and meta.get('report_meta'):
        for label, value in meta['report_meta']:
            ws.append([f'{label} {value}'])
            cell = ws[ws.max_row][0]
            cell.font = Font(bold=True, size=11)
            cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
            merge_row(ws.max_row, ncols)

    # 4) Строка по центру (например «Смена 1»)
    if table.get('title_row'):
        ws.append([table['title_row']])
        ws[ws.max_row][0].font = Font(bold=True, size=13)
        ws[ws.max_row][0].alignment = Alignment(horizontal='center')
        merge_row(ws.max_row, ncols)

    # 6) Шапка таблицы — жирная белая на тёмно-синем, по центру
    header_row = ws.max_row
    if columns:
        two_row = (len(columns) >= 2
                   and str(columns[0]).startswith('Код')
                   and str(columns[1]).startswith('Заводской'))
        if two_row:
            ws.append(['Код:', ''] + list(columns[2:]))
            ws.merge_cells(start_row=ws.max_row, start_column=1,
                           end_row=ws.max_row, end_column=2)
            header_row = ws.max_row
            for cell in ws[header_row]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal='center', vertical='center')
            ws.append(['Продукта', 'Заводской'] + [''] * max(0, len(columns) - 2))
            header_row = ws.max_row
            for cell in ws[header_row]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal='center', vertical='center')
        else:
            ws.append(columns)
            header_row = ws.max_row
            for cell in ws[header_row]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal='center', vertical='center')

    # 7) Данные
    for row in table.get('rows') or []:
        ws.append([_fmt_cell(v) for v in row])

    # 8) Итог — жирный
    if table.get('total_row'):
        ws.append([_fmt_cell(v) for v in table['total_row']])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)

    if table.get('note'):
        ws.append([])
        ws.append([table['note']])

    if columns:
        # Ширина колонок по количеству символов в заголовке, данных и итоге
        col_lens = [len(str(c)) for c in columns]
        for row in table.get('rows') or []:
            for i, cell in enumerate(row):
                if i < len(col_lens):
                    col_lens[i] = max(col_lens[i], len(str(cell)))
        tr = table.get('total_row')
        if tr:
            for i, cell in enumerate(tr):
                if i < len(col_lens):
                    col_lens[i] = max(col_lens[i], len(str(cell)))
        caps = []
        for ln in col_lens:
            width = min(70, max(8, int(ln * 1.2) + 2))
            caps.append(width)
        for col_idx, width in enumerate(caps, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width
        # Страховка: если текст длиннее ширины колонки — перенос на новую строку
        for row_idx in range(1, ws.max_row + 1):
            for col_idx, cw in enumerate(caps, start=1):
                cell = ws.cell(row=row_idx, column=col_idx)
                if cell.value is not None and len(str(cell.value)) > cw:
                    cell.alignment = Alignment(wrap_text=True, vertical='top')

    ws.freeze_panes = f'A{header_row + 1}'


def export_tables_xlsx(meta, tables):
    """Каждая таблица отчёта — отдельный лист Excel (мета-строки — на первом)."""
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for idx, table in enumerate(tables, start=1):
        ws = wb.create_sheet(f'Лист{idx}')
        _write_report_sheet(ws, meta, table, write_meta=(idx == 1))
    buf = io.BytesIO()
    wb.save(buf)
    return meta['filename_xlsx'], buf.getvalue()


def build_day_chart_xlsx(meta, chart_data):
    """График продукции за сутки в Excel (тестовый режим).

    Сутки делятся на 4 части по 6 часов; каждая часть — отдельный график
    (столбцы по часам с подписью количества над каждым столбиком).
    Все 4 графика размещаются на одном листе A4 (альбомная ориентация).
    """
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.chart.label import DataLabelList
    from openpyxl.styles import Font
    from openpyxl.worksheet.properties import PageSetupProperties

    labels = chart_data.get('labels') or []                       # 'HH:MM' по минутам
    data = (chart_data.get('datasets') or [{}])[0].get('data') or []
    details = chart_data.get('details') or []

    # Агрегация по часам: количество за каждый час суток
    per_hour = [0] * 24
    hour_products = {}  # час -> {код: [сумма, цвет]}
    for lbl, val, det in zip(labels, data, details):
        if not lbl or ':' not in str(lbl):
            continue
        try:
            h = int(str(lbl).split(':')[0])
        except ValueError:
            continue
        v = int(val or 0)
        per_hour[h] += v
        if det:
            code = det.get('code')
            hour_products.setdefault(h, {})
            item = hour_products[h].setdefault(code, [0, det.get('color') or '#6c757d'])
            item[0] += v

    # Доминирующий продукт/цвет каждого часа
    hour_colors = ['#4472C4'] * 24
    for h in range(24):
        prods = hour_products.get(h) or {}
        if prods:
            best = max(prods, key=lambda k: prods[k][0])
            hour_colors[h] = prods[best][1] or '#4472C4'

    wb = Workbook()
    ws = wb.active
    ws.title = 'График за сутки'
    # Данные графика — на отдельном скрытом листе (пользователю не видны)
    ws_data = wb.create_sheet('Данные')
    ws_data.sheet_state = 'hidden'

    # Один лист A4, альбомная ориентация, вписать в одну страницу
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = 9  # A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)

    ws['A1'] = meta.get('title', 'График за сутки')
    ws['A1'].font = Font(bold=True, size=14)
    ws['A2'] = f'Период: {meta.get("period_label", "")} · Счетчик: {meta.get("counter", "")}'
    ws['A2'].font = Font(bold=True, size=11)

    sections = [
        ('00:00 – 06:00', range(0, 6)),
        ('06:00 – 12:00', range(6, 12)),
        ('12:00 – 18:00', range(12, 18)),
        ('18:00 – 24:00', range(18, 24)),
    ]

    # Данные секций на скрытом листе: часы/значения в колонках A..H (строки 1-6)
    for si, (_title, hrs) in enumerate(sections):
        col = 1 + si * 2  # A, C, E, G
        for j, h in enumerate(hrs):
            ws_data.cell(row=1 + j, column=col, value=f'{h:02d}:00')
            ws_data.cell(row=1 + j, column=col + 1, value=per_hour[h])

    anchors = [
        ('A4', 0), ('H4', 1),
        ('A22', 2), ('H22', 3),
    ]
    for (anchor, si) in anchors:
        _title, hrs = sections[si]
        col = 1 + si * 2
        chart = BarChart()
        chart.type = 'col'
        chart.title = _title
        chart.width = 12.5
        chart.height = 9.5
        data_ref = Reference(ws_data, min_col=col + 1, min_row=1, max_row=6)
        cats_ref = Reference(ws_data, min_col=col, min_row=1, max_row=6)
        chart.add_data(data_ref, titles_from_data=False)
        chart.set_categories(cats_ref)
        # Подписи количества над каждым столбиком
        chart.dataLabels = DataLabelList()
        chart.dataLabels.showVal = True
        chart.dataLabels.numFmt = '0'
        chart.dataLabels.dLblPos = 'outEnd'
        chart.legend = None
        ws.add_chart(chart, anchor)

    buf = io.BytesIO()
    wb.save(buf)
    return meta.get('filename_xlsx', 'chart_day.xlsx'), buf.getvalue()


def export_tables_csv(meta, tables):
    """Каждая таблица отчёта — блок строк в одном CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';')
    writer.writerow([meta.get('title', 'Отчёт')])
    writer.writerow([f'Сформирован: {meta.get("generated_at", "")}'])
    # Шапка отчёта (мета-строки)
    if meta.get('report_meta'):
        for label, value in meta['report_meta']:
            writer.writerow([f'{label} {value}'])
    writer.writerow([])
    for table in tables:
        if table.get('title_row'):
            writer.writerow([table['title_row']])
        columns = table.get('columns') or []
        if columns:
            writer.writerow(columns)
        for row in table.get('rows') or []:
            writer.writerow([_fmt_cell(v) for v in row])
        if table.get('total_row'):
            writer.writerow([_fmt_cell(v) for v in table['total_row']])
        writer.writerow([])
    return meta['filename_csv'], buf.getvalue().encode('utf-8-sig')


# ---------------------------------------------------------------------------
# Пакетный экспорт нескольких отчётов (сравнение) — один файл, лист на отчёт
# ---------------------------------------------------------------------------

def export_reports_bundle_xlsx(items):
    """Несколько отчётов — один Excel-файл, отдельный лист на каждый отчёт.

    items: список {'meta': {...}, 'tables': [...]}. На каждом листе — свой
    заголовок, «Сформирован», мета-строки отчёта и все его таблицы
    последовательно (пустая строка между таблицами).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    header_font, header_fill, _ = _xlsx_style()

    wb = Workbook()
    wb.remove(wb.active)
    for idx, item in enumerate(items, start=1):
        ws = wb.create_sheet(f'Отчет {idx}')
        meta = item.get('meta') or {}
        tables = item.get('tables') or []
        ncols = max([len((t.get('columns') or [])) for t in tables] or [1])

        def merge_row(row_idx):
            if ncols > 1:
                ws.merge_cells(start_row=row_idx, start_column=1,
                               end_row=row_idx, end_column=ncols)

        # Заголовок отчёта + «Сформирован» + мета-строки — в начале листа
        ws.append([meta.get('title', 'Отчёт')])
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center', vertical='top', wrap_text=True)
        ws.row_dimensions[1].height = 22.5
        merge_row(1)

        ws.append([f'Сформирован: {meta.get("generated_at", "")}'])
        ws[ws.max_row][0].alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
        merge_row(ws.max_row)

        if meta.get('report_meta'):
            for label, value in meta['report_meta']:
                ws.append([f'{label} {value}'])
                cell = ws[ws.max_row][0]
                cell.font = Font(bold=True, size=11)
                cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
                merge_row(ws.max_row)

        header_row = None
        for table in tables:
            if table.get('title_row'):
                ws.append([table['title_row']])
                ws[ws.max_row][0].font = Font(bold=True, size=13)
                ws[ws.max_row][0].alignment = Alignment(horizontal='center')
                merge_row(ws.max_row)
            columns = table.get('columns') or []
            if columns:
                two_row = (len(columns) >= 2
                           and str(columns[0]).startswith('Код')
                           and str(columns[1]).startswith('Заводской'))
                if two_row:
                    ws.append(['Код:', ''] + list(columns[2:]))
                    ws.merge_cells(start_row=ws.max_row, start_column=1,
                                   end_row=ws.max_row, end_column=2)
                    if header_row is None:
                        header_row = ws.max_row
                    for cell in ws[ws.max_row]:
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = Alignment(horizontal='center', vertical='center')
                    ws.append(['Продукта', 'Заводской'] + [''] * max(0, len(columns) - 2))
                    if header_row is None:
                        header_row = ws.max_row
                    for cell in ws[ws.max_row]:
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = Alignment(horizontal='center', vertical='center')
                else:
                    ws.append(columns)
                    if header_row is None:
                        header_row = ws.max_row
                    for cell in ws[ws.max_row]:
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = Alignment(horizontal='center', vertical='center')
            for row in table.get('rows') or []:
                ws.append([_fmt_cell(v) for v in row])
            if table.get('total_row'):
                ws.append([_fmt_cell(v) for v in table['total_row']])
                for cell in ws[ws.max_row]:
                    cell.font = Font(bold=True)
            if table.get('note'):
                ws.append([])
                ws.append([table['note']])
            ws.append([])  # разделитель между таблицами

        # Ширина колонок — по символам (максимум по всем таблицам листа)
        caps = {}
        for table in tables:
            columns = table.get('columns') or []
            if not columns:
                continue
            col_lens = [len(str(c)) for c in columns]
            for row in table.get('rows') or []:
                for i, cell in enumerate(row):
                    if i < len(col_lens):
                        col_lens[i] = max(col_lens[i], len(str(cell)))
            tr = table.get('total_row')
            if tr:
                for i, cell in enumerate(tr):
                    if i < len(col_lens):
                        col_lens[i] = max(col_lens[i], len(str(cell)))
            for i, ln in enumerate(col_lens, start=1):
                caps[i] = max(caps.get(i, 0), min(70, max(8, int(ln * 1.2) + 2)))
        for col_idx, width in caps.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = width
        if header_row:
            ws.freeze_panes = f'A{header_row + 1}'

    buf = io.BytesIO()
    wb.save(buf)
    return 'reports_comparison.xlsx', buf.getvalue()


def export_reports_bundle_csv(items):
    """Несколько отчётов — один CSV: блоки отчётов разделены пустой строкой."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';')
    for item in items:
        meta = item.get('meta') or {}
        writer.writerow([meta.get('title', 'Отчёт')])
        writer.writerow([f'Сформирован: {meta.get("generated_at", "")}'])
        if meta.get('report_meta'):
            for label, value in meta['report_meta']:
                writer.writerow([f'{label} {value}'])
        writer.writerow([])
        for table in item.get('tables') or []:
            if table.get('title_row'):
                writer.writerow([table['title_row']])
            columns = table.get('columns') or []
            if columns:
                writer.writerow(columns)
            for row in table.get('rows') or []:
                writer.writerow([_fmt_cell(v) for v in row])
            if table.get('total_row'):
                writer.writerow([_fmt_cell(v) for v in table['total_row']])
            writer.writerow([])
        writer.writerow([])
    return 'reports_comparison.csv', buf.getvalue().encode('utf-8-sig')
