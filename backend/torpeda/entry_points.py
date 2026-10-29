"""Точки входа по артикулам из отчёта кабинета WB.

API WB не отдаёт отчёт «Аналитика → Точки входа», он есть только в кабинете продавца (Excel). Загружаем скачанный
файл: колонки находим по заголовкам, показатели сохраняем как есть. Повторная загрузка заменяет данные тех же
артикулов и дней (точка входа + день), так что можно загружать отчёты за разные периоды подряд."""

from __future__ import annotations

import io
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from torpeda.db import DEFAULT_ACCOUNT_ID
from torpeda.db.models import EntryPoint

ACC = DEFAULT_ACCOUNT_ID
NM_HEADS = ("артикул wb", "nmid", "nm id", "nm_id", "артикул вб", "артикул")
POINT_HEADS = ("точка входа", "точки входа", "источник", "раздел", "канал")
DAY_HEADS = ("дата", "день")
SKIP_HEADS = ("артикул продавца", "название", "бренд", "предмет", "категория", "vendor")
AVG_HINTS = ("%", "конверс", "ctr", "средн", "позици")  # такие показатели не складываются, а усредняются


def _num(v) -> float | None:
    if isinstance(v, bool) or v in (None, ""):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(Decimal(str(v).replace("%", "").replace(",", ".").replace(" ", "").replace("\xa0", "")))
    except InvalidOperation:
        return None


def _day(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(str(v).strip()[:10], fmt).date()
        except ValueError:
            pass
    return None


def _find(header: list[str], names: tuple[str, ...], exact: bool = False) -> int | None:
    for name in names:  # раньше в списке — важнее
        for i, h in enumerate(header):
            if h == name or (not exact and name in h and not any(x in h for x in SKIP_HEADS)):
                return i
    return None


def parse(content: bytes) -> list[dict]:
    """Строки отчёта: артикул, точка входа, день (если есть), показатели."""
    try:
        ws = load_workbook(io.BytesIO(content), data_only=True, read_only=True).worksheets[0]
    except Exception as e:  # noqa: BLE001 - любой нечитаемый файл — одна и та же понятная ошибка
        raise ValueError("не получилось открыть файл как Excel (.xlsx)") from e
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    for hi, raw in enumerate(rows[:15]):  # заголовок может быть не в первой строке
        header = [str(h).strip().lower() if h is not None else "" for h in raw]
        nm_i = _find(header, NM_HEADS)
        if nm_i is not None:
            break
    else:
        raise ValueError("не нашёл колонку «Артикул WB» — это точно отчёт «Точки входа»?")
    names = [str(h).strip() if h is not None else "" for h in rows[hi]]
    day_i = _find(header, DAY_HEADS)
    point_i = _find(header, POINT_HEADS)
    if point_i is None:  # первая текстовая колонка после артикула
        for i in range(len(header)):
            if i not in (nm_i, day_i) and header[i] and not any(x in header[i] for x in SKIP_HEADS):
                sample = [r[i] for r in rows[hi + 1 : hi + 20] if i < len(r) and r[i] not in (None, "")]
                if sample and all(_num(v) is None for v in sample):
                    point_i = i
                    break
    if point_i is None:
        raise ValueError("не нашёл колонку «Точка входа»")
    out = []
    for r in rows[hi + 1 :]:
        r = list(r) + [None] * (len(names) - len(r))
        nm = _num(r[nm_i])
        point = str(r[point_i] or "").strip()
        if nm is None or not point:
            continue
        metrics = {}
        for i, name in enumerate(names):
            if name and i not in (nm_i, point_i, day_i) and not any(x in header[i] for x in SKIP_HEADS):
                if (v := _num(r[i])) is not None:
                    metrics[name] = v
        out.append({"nm_id": int(nm), "point": point, "day": _day(r[day_i]) if day_i is not None else None, "metrics": metrics})
    if not out:
        raise ValueError("в файле нет строк с артикулом и точкой входа")
    return out


def import_files(s: Session, files: list[tuple[str, bytes]]) -> dict:
    report = []
    for filename, content in sorted(files):
        try:
            items = parse(content)
        except ValueError as e:
            report.append({"file": filename, "error": str(e)})
            continue
        keys = {(it["nm_id"], it["point"], it["day"]) for it in items}
        for nm, point, day in keys:
            cond = [EntryPoint.account_id == ACC, EntryPoint.nm_id == nm, EntryPoint.point == point]
            cond.append(EntryPoint.day.is_(None) if day is None else EntryPoint.day == day)
            s.execute(delete(EntryPoint).where(*cond))
        for it in items:
            s.add(EntryPoint(account_id=ACC, nm_id=it["nm_id"], point=it["point"], day=it["day"],
                             metrics=json.dumps(it["metrics"], ensure_ascii=False), source_file=filename[-300:]))
        report.append({"file": filename, "rows": len(items), "articles": len({it["nm_id"] for it in items})})
    s.commit()
    return {"files": report, "rows": sum(r.get("rows", 0) for r in report)}


def summary(s: Session, nm_id: int | None = None) -> dict:
    """Точки входа по артикулам за всё загруженное время: суммы показателей, процентные — средние."""
    q = select(EntryPoint).where(EntryPoint.account_id == ACC)
    if nm_id is not None:
        q = q.where(EntryPoint.nm_id == nm_id)
    groups: dict[tuple[int, str], dict] = {}
    columns: list[str] = []
    days: list[date] = []
    for row in s.scalars(q):
        g = groups.setdefault((row.nm_id, row.point), {"sum": {}, "n": {}})
        if row.day:
            days.append(row.day)
        for k, v in json.loads(row.metrics).items():
            if k not in columns:
                columns.append(k)
            g["sum"][k] = g["sum"].get(k, 0) + v
            g["n"][k] = g["n"].get(k, 0) + 1
    out = []
    for (nm, point), g in groups.items():
        vals = {k: (v / g["n"][k] if any(h in k.lower() for h in AVG_HINTS) else v) for k, v in g["sum"].items()}
        out.append({"nm_id": nm, "point": point, **{f"m{columns.index(k)}": round(v, 2) for k, v in vals.items()}})
    out.sort(key=lambda r: (r["nm_id"], -(r.get("m0") or 0)))
    return {"columns": columns, "rows": out, "date_from": min(days, default=None), "date_to": max(days, default=None)}
