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


def build_comparison_xlsx(meta, lines_data):
    """Отчёт по нескольким линиям: лист на каждую линию + сводка."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    header_font, header_fill, title_font = _xlsx_style()

    wb = Workbook()
    wb.remove(wb.active)

    summary_ws = wb.create_sheet('Сводка')
    summary_ws.append(['Сравнительный отчёт по линиям'])
    summary_ws['A1'].font = title_font
    summary_ws.append([f'Сформирован: {meta["generated_at"]}'])
    summary_ws.append([])
    summary_ws.append(['Линия', 'Цех', 'Период с', 'Период по', 'Всего, шт.'])
    for cell in summary_ws[4]:
        cell.font = header_font
        cell.fill = header_fill
    for ld in lines_data:
        summary_ws.append([
            ld['name'], ld['shop_name'],
            ld['from'][:16].replace('T', ' '), ld['to'][:16].replace('T', ' '),
            ld['total'],
        ])
    grand_total = sum(ld['total'] for ld in lines_data)
    summary_ws.append([])
    summary_ws.append(['ИТОГО ПО ВСЕМ ЛИНИЯМ', '', '', '', grand_total])
    for cell in summary_ws[summary_ws.max_row]:
        cell.font = Font(bold=True)
    for col, w in zip('ABCDE', [46, 26, 18, 18, 12]):
        summary_ws.column_dimensions[col].width = w

    for ld in lines_data:
        ws = wb.create_sheet(f"Л{ld['line_id']}")
        ws.append([f'Линия: {ld["name"]}'])
        ws['A1'].font = title_font
        ws.append([f'Цех: {ld["shop_name"]} · Период: {ld["from"][:16].replace("T", " ")} — {ld["to"][:16].replace("T", " ")}'])
        ws.append([])
        headers = ['Время', 'Код продукта', 'Продукт', 'Кол-во, шт.']
        ws.append(headers)
        for cell in ws[4]:
            cell.font = header_font
            cell.fill = header_fill
        run_total = 0
        last_assign = None
        for pt in ld['series']:
            if pt['assignment_id'] != last_assign:
                run_total = 0
                last_assign = pt['assignment_id']
            run_total += pt['count']
            ws.append([pt['minute'], pt['product_code'] or '—', pt['product_name'] or '—', pt['count']])
        total_row = ws.max_row + 1
        ws.cell(row=total_row, column=3, value='ИТОГО:').font = Font(bold=True)
        ws.cell(row=total_row, column=4, value=ld['total']).font = Font(bold=True)
        for col, w in zip('ABCD', [10, 14, 40, 12]):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = 'A5'

    buf = io.BytesIO()
    wb.save(buf)
    return meta['filename_xlsx'], buf.getvalue()


def build_comparison_csv(meta, lines_data):
    """CSV-версия сравнения (лист = блок строк с заголовком линии)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';')
    writer.writerow(['Сравнительный отчёт по линиям'])
    writer.writerow([f'Сформирован: {meta["generated_at"]}'])
    writer.writerow([])
    for ld in lines_data:
        writer.writerow([f'Линия: {ld["name"]} ({ld["from"][:16].replace("T", " ")} — {ld["to"][:16].replace("T", " ")})'])
        writer.writerow(['Время', 'Код продукта', 'Продукт', 'Кол-во, шт.'])
        run_total = 0
        last_assign = None
        for pt in ld['series']:
            if pt['assignment_id'] != last_assign:
                run_total = 0
                last_assign = pt['assignment_id']
            run_total += pt['count']
            writer.writerow([pt['minute'], pt['product_code'] or '—', pt['product_name'] or '—', pt['count']])
        writer.writerow(['ИТОГО:', '', '', ld['total']])
        writer.writerow([])
    writer.writerow(['ИТОГО ПО ВСЕМ ЛИНИЯМ:', '', '', sum(ld['total'] for ld in lines_data)])
    return meta['filename_csv'], buf.getvalue().encode('utf-8-sig')


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


def export_tables_xlsx(meta, tables):
    """Каждая таблица отчёта — отдельный лист Excel.

    Формат по образцу: объединённый заголовок отчёта по ширине листа,
    «Сформирован:», шапка отчёта (мета-строки, каждая объединена по ширине),
    шапка таблицы (жирная, по центру, на тёмно-синем фоне), данные, итог.
    Ширина колонок — по количеству символов.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    header_font, header_fill, _ = _xlsx_style()

    def merge_row(ws, row_idx, ncols):
        if ncols > 1:
            ws.merge_cells(start_row=row_idx, start_column=1,
                           end_row=row_idx, end_column=ncols)

    wb = Workbook()
    wb.remove(wb.active)
    for idx, table in enumerate(tables, start=1):
        ws = wb.create_sheet(f'Лист{idx}')
        columns = table.get('columns') or []
        ncols = max(len(columns), 1)
        last_col = get_column_letter(ncols)

        # 1) Заголовок отчёта — объединён по ширине, по центру
        ws.append([meta.get('title', 'Отчёт')])
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center', vertical='top', wrap_text=True)
        ws.row_dimensions[1].height = 22.5
        merge_row(ws, 1, ncols)

        # 2) Сформирован
        ws.append([f'Сформирован: {meta.get("generated_at", "")}'])
        ws[ws.max_row][0].alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
        merge_row(ws, ws.max_row, ncols)

        # 3) Шапка отчёта (мета-строки) — только на первом листе
        if idx == 1 and meta.get('report_meta'):
            for label, value in meta['report_meta']:
                ws.append([f'{label} {value}'])
                cell = ws[ws.max_row][0]
                cell.font = Font(bold=True, size=11)
                cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
                merge_row(ws, ws.max_row, ncols)

        # 4) Название дополнительной таблицы (листы 2+), если отличается
        if idx > 1 and table.get('title'):
            ws.append([table['title']])
            ws[ws.max_row][0].font = Font(bold=True, size=12)
            merge_row(ws, ws.max_row, ncols)

        # 5) Строка по центру (например «Смена 1»)
        if table.get('title_row'):
            ws.append([table['title_row']])
            ws[ws.max_row][0].font = Font(bold=True, size=13)
            ws[ws.max_row][0].alignment = Alignment(horizontal='center')
            merge_row(ws, ws.max_row, ncols)

        # 6) Шапка таблицы — жирная белая на тёмно-синем, по центру
        header_row = ws.max_row
        if columns:
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

    buf = io.BytesIO()
    wb.save(buf)
    return meta['filename_xlsx'], buf.getvalue()


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
        if table.get('title'):
            writer.writerow([table['title']])
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
