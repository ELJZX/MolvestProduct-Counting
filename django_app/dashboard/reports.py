"""Формирование отчётов: Excel (openpyxl) и CSV."""
import csv
import io

from django.utils import timezone


def _xlsx_style():
    """Общие стили Excel-отчётов."""
    from openpyxl.styles import Font, PatternFill
    return (
        Font(bold=True, color='FFFFFF'),
        PatternFill('solid', fgColor='1F4E78'),
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
    """Каждая таблица отчёта — отдельный лист Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    header_font, header_fill, title_font = _xlsx_style()

    wb = Workbook()
    wb.remove(wb.active)
    for idx, table in enumerate(tables, start=1):
        ws = wb.create_sheet(f'Лист{idx}')
        ws.append([meta.get('title', 'Отчёт')])
        ws['A1'].font = title_font
        ws.append([f'{meta.get("period_label", "")} · Счетчик: {meta.get("counter", "")}'])
        ws.append([f'Сформирован: {meta.get("generated_at", "")}'])
        ws.append([])
        if table.get('title'):
            ws.append([table['title']])
            ws[ws.max_row][0].font = Font(bold=True, size=12)
        columns = table.get('columns') or []
        if columns:
            ws.append(columns)
            for cell in ws[ws.max_row]:
                cell.font = header_font
                cell.fill = header_fill
        for row in table.get('rows') or []:
            ws.append([_fmt_cell(v) for v in row])
        if table.get('total_row'):
            ws.append([_fmt_cell(v) for v in table['total_row']])
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
        if table.get('note'):
            ws.append([])
            ws.append([table['note']])
        if columns:
            for col_idx in range(1, len(columns) + 1):
                letter = get_column_letter(col_idx)
                width = max(10, min(50, (max([len(str(c)) for c in columns]) if columns else 10) + 4))
                ws.column_dimensions[letter].width = width
        ws.freeze_panes = 'A5'

    buf = io.BytesIO()
    wb.save(buf)
    return meta['filename_xlsx'], buf.getvalue()


def export_tables_csv(meta, tables):
    """Каждая таблица отчёта — блок строк в одном CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';')
    writer.writerow([meta.get('title', 'Отчёт')])
    writer.writerow([f'{meta.get("period_label", "")} · Счетчик: {meta.get("counter", "")}'])
    writer.writerow([f'Сформирован: {meta.get("generated_at", "")}'])
    writer.writerow([])
    for table in tables:
        if table.get('title'):
            writer.writerow([table['title']])
        columns = table.get('columns') or []
        if columns:
            writer.writerow(columns)
        for row in table.get('rows') or []:
            writer.writerow([_fmt_cell(v) for v in row])
        if table.get('total_row'):
            writer.writerow([_fmt_cell(v) for v in table['total_row']])
        writer.writerow([])
    return meta['filename_csv'], buf.getvalue().encode('utf-8-sig')
