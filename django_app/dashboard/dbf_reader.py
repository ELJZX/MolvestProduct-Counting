"""Чтение и анализ файлов DBF (dBase III) — запасной источник данных.

Файлы вида 20442023.dbf: первые 4 символа имени — код объекта
(цех/линия/счётчик), оставшиеся 4 — год. Формат записи (41 байт):
    DATE   (8, D) — дата YYYYMMDD
    TIME   (5, C) — время HH:MM
    COUNT  (7, N) — количество продукции за минуту
    KOD    (5, N) — код продукта (001..999)
    KEY, AVR, DNA, PIT, KTIME, AVRTIME, PITTIME, FS, ADATCH — служебные

Записи отсортированы по дате/времени; для быстрого поиска используется
бинарный поиск по ключу "YYYYMMDDHH:MM" (лексикографически корректный,
т.к. значения дополнены нулями). Если файл окажется не отсортирован,
сканирование автоматически перезапускается с начала.
"""
import datetime
import os
import struct

from django.utils import timezone

_MINUTE = datetime.timedelta(minutes=1)


def _parse_header(data):
    """Разбирает заголовок DBF: (version, record_count, header_size, record_size, fields)."""
    version = data[0]
    record_count = struct.unpack('<I', data[4:8])[0]
    header_size = struct.unpack('<H', data[8:10])[0]
    record_size = struct.unpack('<H', data[10:12])[0]
    fields = []
    i = 32
    while i + 32 <= header_size - 1:
        if data[i] == 0x0D:
            break
        name = data[i:i + 11].split(b'\x00')[0].decode('cp866', errors='replace').strip()
        fields.append({
            'name': name,
            'type': chr(data[i + 11]),
            'length': data[i + 16],
            'decimals': data[i + 17],
        })
        i += 32
    return version, record_count, header_size, record_size, fields


def _field_layout(fields):
    """Смещения полей внутри записи: name -> (offset, length, type)."""
    offsets = {}
    pos = 1  # первый байт записи — флаг удаления
    for fd in fields:
        offsets[fd['name']] = (pos, fd['length'], fd['type'])
        pos += fd['length']
    return offsets


def _decode(rec, offsets, name):
    o, ln, _t = offsets[name]
    return rec[o:o + ln]


def _decode_minute(rec, offsets):
    """Возвращает naive datetime по DATE+TIME или None."""
    date_raw = _decode(rec, offsets, 'DATE').strip()
    if not date_raw or len(date_raw) != 8:
        return None
    time_raw = _decode(rec, offsets, 'TIME').strip()
    try:
        return datetime.datetime.strptime(
            date_raw.decode('ascii', 'replace') + ' ' + time_raw.decode('cp866', 'replace'),
            '%Y%m%d %H:%M',
        )
    except (ValueError, UnicodeDecodeError):
        return None


def _minute_key(rec, offsets):
    """Ключ записи 'YYYYMMDDHH:MM' для лексикографического сравнения."""
    date_raw = _decode(rec, offsets, 'DATE').strip()
    time_raw = _decode(rec, offsets, 'TIME').strip()
    return (date_raw + time_raw).decode('ascii', 'replace')


def _num(rec, offsets, name):
    v = _decode(rec, offsets, name).strip()
    if not v:
        return 0
    try:
        return int(v)
    except ValueError:
        return 0


def _open_layout(path):
    with open(path, 'rb') as f:
        head = f.read(512)
    if not head:
        raise ValueError('Файл пуст')
    version, record_count, header_size, record_size, fields = _parse_header(head)
    offsets = _field_layout(fields)
    return version, record_count, header_size, record_size, offsets


def _make_aware(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _floor_minute(dt):
    local = timezone.localtime(dt)
    return local.replace(second=0, microsecond=0)


def _ceil_minute(dt):
    """Потолок до минуты: 08:30:45 -> 08:31, 08:30:00 -> 08:30."""
    local = timezone.localtime(dt)
    if local.second or local.microsecond:
        return (local + _MINUTE).replace(second=0, microsecond=0)
    return local.replace(second=0, microsecond=0)


def file_info(path):
    """Краткая информация о файле: {filename, path, record_count, first, last, ...}.

    first/last — aware datetime первой и последней непустой записи.
    """
    base = os.path.splitext(os.path.basename(path))[0]
    code = base[:4] if len(base) >= 8 else base
    year = base[4:8] if len(base) >= 8 and base[4:8].isdigit() else ''
    try:
        _ver, record_count, header_size, record_size, offsets = _open_layout(path)
    except Exception:
        return None

    first = last = None
    with open(path, 'rb') as f:
        # первая непустая запись
        f.seek(header_size)
        for _ in range(record_count):
            rec = f.read(record_size)
            if len(rec) < record_size:
                break
            m = _decode_minute(rec, offsets)
            if m:
                first = m
                break
        # последняя непустая (идём с конца)
        idx = record_count - 1
        while idx >= 0 and last is None and idx > record_count - 50:
            f.seek(header_size + idx * record_size)
            rec = f.read(record_size)
            m = _decode_minute(rec, offsets)
            if m:
                last = m
                break
            idx -= 1
    name = f'Объект {code}' + (f' · {year} г.' if year else '')
    first = _make_aware(first)
    last = _make_aware(last)
    return {
        'filename': os.path.basename(path),
        'path': path,
        'code': code,
        'year': year,
        'display_name': name,
        'record_count': record_count,
        'first': first,
        'last': last,
        'first_str': timezone.localtime(first).strftime('%d.%m.%Y %H:%M') if first else '—',
        'last_str': timezone.localtime(last).strftime('%d.%m.%Y %H:%M') if last else '—',
        'first_iso': first.isoformat() if first else None,
        'last_iso': last.isoformat() if last else None,
    }


def list_dbf_files(dbf_dir):
    """Список *.dbf в папке с информацией по каждому файлу."""
    if not dbf_dir or not os.path.isdir(dbf_dir):
        return []
    out = []
    for name in sorted(os.listdir(dbf_dir)):
        if not name.lower().endswith('.dbf'):
            continue
        info = file_info(os.path.join(dbf_dir, name))
        if info:
            out.append(info)
    return out


def iter_minutes(path, from_dt, to_dt, kod=None):
    """Генератор записей в диапазоне [from_dt, to_dt) с фильтром по коду.

    Возвращает словари: {minute (aware), count, kod, kod_str}.
    Быстрый старт через бинарный поиск; при нарушении сортировки файла
    сканирование перезапускается с начала.
    """
    from_dt = _make_aware(from_dt)
    to_dt = _make_aware(to_dt)
    _ver, record_count, header_size, record_size, offsets = _open_layout(path)
    from_key = _floor_minute(from_dt).strftime('%Y%m%d%H:%M')
    to_key = _ceil_minute(to_dt).strftime('%Y%m%d%H:%M')
    if kod:
        kod = str(kod).strip().zfill(3)

    def decode(rec):
        m = _decode_minute(rec, offsets)
        if m is None:
            return None
        count = _num(rec, offsets, 'COUNT')
        kod_num = _num(rec, offsets, 'KOD')
        kod_str = f'{kod_num:03d}' if kod_num else None
        return {
            'minute': _make_aware(m),
            'count': count,
            'kod': kod_num,
            'kod_str': kod_str,
        }

    def read_at(f, index):
        f.seek(header_size + index * record_size)
        rec = f.read(record_size)
        return rec if len(rec) == record_size else None

    def scan(start, f):
        """Линейное сканирование от start до to_key; (rows, stopped, unsorted)."""
        rows = []
        last_key = None
        unsorted = False
        for idx in range(start, record_count):
            rec = read_at(f, idx)
            if rec is None:
                break
            key = _minute_key(rec, offsets)
            if last_key is not None and key < last_key:
                unsorted = True
                break
            last_key = key
            if key >= to_key:  # полуинтервал [from, to)
                break
            row = decode(rec)
            if row is None:
                continue
            if kod and row['kod_str'] != kod:
                continue
            rows.append(row)
        return rows, unsorted

    with open(path, 'rb') as f:
        # бинарный поиск первой записи >= from_key
        lo, hi = 0, record_count
        while lo < hi:
            mid = (lo + hi) // 2
            rec = read_at(f, mid)
            k = _minute_key(rec, offsets) if rec else '\xff' * 16
            if k < from_key:
                lo = mid + 1
            else:
                hi = mid
        rows, unsorted = scan(lo, f)
        if unsorted:
            # файл не отсортирован — честный полный проход
            rows, _ = scan(0, f)
        for r in rows:
            yield r


def read_minutes(path, from_dt, to_dt, kod=None):
    """Все минутные записи диапазона списком (для графиков и подробных отчётов)."""
    return list(iter_minutes(path, from_dt, to_dt, kod=kod))


# ---------------------------------------------------------------------------
# Коды счётчиков и файлы за период
# ---------------------------------------------------------------------------

def _code_from_filename(filename):
    """Код счётчика из имени файла: '20442023.dbf' -> '2044' (и год '2023')."""
    base = os.path.splitext(os.path.basename(filename))[0]
    if len(base) >= 8 and base[:4].isdigit() and base[4:8].isdigit():
        return base[:4], base[4:8]
    if len(base) >= 4 and base[:4].isdigit():
        return base[:4], ''
    return base, ''


def list_counter_codes(dbf_dir):
    """Коды счётчиков, найденные в именах файлов.

    Возвращает dict: code -> {'files': [...], 'first': aware|None, 'last': aware|None}.
    """
    files = list_dbf_files(dbf_dir)
    by_code = {}
    for f in files:
        code, _year = _code_from_filename(f['filename'])
        entry = by_code.setdefault(code, {'files': [], 'first': None, 'last': None})
        entry['files'].append(f)
    for code, entry in by_code.items():
        entry['files'].sort(key=lambda x: x['filename'])
        firsts = [f['first'] for f in entry['files'] if f['first']]
        lasts = [f['last'] for f in entry['files'] if f['last']]
        entry['first'] = min(firsts) if firsts else None
        entry['last'] = max(lasts) if lasts else None
    return by_code


def find_files_for_period(dbf_dir, code, from_dt, to_dt):
    """Файлы счётчика, покрывающие период [from_dt, to_dt).

    Берутся файлы, у которых интервал данных пересекается с запрошенным
    периодом (например, 20442023.dbf и 20442024.dbf для периода через новый год).
    """
    code = str(code).strip()
    out = []
    for f in list_dbf_files(dbf_dir):
        fcode, _year = _code_from_filename(f['filename'])
        if fcode != code:
            continue
        if f['first'] and f['last']:
            if f['last'] < from_dt or f['first'] >= to_dt:
                continue
        out.append(f)
    out.sort(key=lambda x: x['filename'])
    return out


# ---------------------------------------------------------------------------
# Простои (запасной режим)
# ---------------------------------------------------------------------------

def downtime_events(path, from_dt, to_dt):
    """События простоя по файлу DBF.

    В файле DBF запись есть на каждую минуту, поэтому простоем считается
    непрерывный ряд минут с нулевым счётом длительностью более 1 минуты.
    Возвращает список {start, end, minutes, ongoing, product_code, product_name}.
    """
    events = []
    run_start = None
    last = None
    for r in iter_minutes(path, from_dt, to_dt):
        m, count = r['minute'], r['count']
        if count == 0:
            if run_start is None:
                run_start = m
        else:
            if run_start is not None:
                minutes = int((m - run_start).total_seconds() // 60)
                if minutes > 1:
                    events.append({
                        'start': run_start, 'end': m, 'minutes': minutes,
                        'ongoing': False, 'product_code': None, 'product_name': '—',
                    })
                run_start = None
        last = m
    if run_start is not None and last is not None:
        minutes = int((last + _MINUTE - run_start).total_seconds() // 60)
        if minutes > 1:
            events.append({
                'start': run_start, 'end': last + _MINUTE, 'minutes': minutes,
                'ongoing': True, 'product_code': None, 'product_name': '—',
            })
    events.sort(key=lambda e: e['start'])
    return events
