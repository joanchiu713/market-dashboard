"""每日更新 data/sox.json、data/tsm.json、data/txf.json。

資料來源
- 費城半導體指數（^SOX）、台積電 ADR（TSM）：Yahoo Finance chart API（日線收盤）
- 臺指期近月盤後時段（夜盤）：臺灣期貨交易所
    1) 期貨每日交易行情下載（CSV，可一次抓一個月，用來補缺漏）
    2) 期交所 OpenAPI DailyMarketReportFut（只有最新一個交易日，備援）

日期規則
- sox / tsm：美東交易日
- txf：夜盤「起盤日」(台北 D 15:00 起至 D+1 05:00 的 D)。期交所把夜盤歸到下一個營業日，
  所以檔案中交易日期 T 的「盤後」列，起盤日 = T 的前一個營業日。

既有資料不會被覆蓋，只會：新增缺的日期、補上原本是 null 的成交量。
若新抓到的數字和既有資料不同，只印出警告，不改檔。
"""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
ET = ZoneInfo("America/New_York")
TPE = ZoneInfo("Asia/Taipei")
warnings: list[str] = []
added: dict[str, list[str]] = {"sox": [], "tsm": [], "txf": []}


def load(name: str) -> list[dict]:
    p = DATA / f"{name}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else []


def save(name: str, rows: list[dict]) -> None:
    rows.sort(key=lambda r: r["date"])
    (DATA / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0).replace("\n", ""), "utf-8")


# ---------------------------------------------------------------- Yahoo
def yahoo_daily(symbol: str, rng: str = "3mo") -> list[dict]:
    last_err = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}"
        try:
            r = requests.get(url, params={"range": rng, "interval": "1d"}, headers=UA, timeout=30)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
    else:
        raise RuntimeError(f"Yahoo {symbol} 取得失敗：{last_err}")

    ts = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0].get("close") or []
    now_et = datetime.now(ET)
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, ET).date()
        # 今天美股還沒收盤（16:15 ET 前）的數字不是收盤價，略過
        if d == now_et.date() and (now_et.hour, now_et.minute) < (16, 15):
            continue
        out.append({"date": d.isoformat(), "close": round(float(c), 2)})
    return out


def merge_close(name: str, fresh: list[dict], tol: float) -> None:
    rows = load(name)
    have = {r["date"]: r for r in rows}
    for f in fresh:
        old = have.get(f["date"])
        if old is None:
            # 只新增比檔案最早日期更新的資料，避免把很久以前的歷史塞進來
            if rows and f["date"] < rows[0]["date"]:
                continue
            rows.append(f)
            have[f["date"]] = f
            added[name].append(f["date"])
        elif abs(float(old["close"]) - f["close"]) > tol:
            warnings.append(f"{name} {f['date']} 既有 {old['close']}，新來源 {f['close']}（未覆蓋）")
    save(name, rows)


# ---------------------------------------------------------------- TAIFEX
def _num(s) -> float | None:
    s = str(s or "").strip().replace(",", "")
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pick(row: dict, *keys: str):
    for k in row:
        kk = k.strip().lower()
        if any(key.lower() in kk for key in keys):
            return row[k]
    return None


def taifex_csv(start: date, end: date) -> list[dict]:
    """期貨每日交易行情下載，回傳 [{trade_date, session, month, close, chg, vol}]"""
    r = requests.post(
        "https://www.taifex.com.tw/cht/3/futDataDown",
        data={
            "down_type": "1",
            "commodity_id": "TX",
            "commodity_id2": "",
            "queryStartDate": start.strftime("%Y/%m/%d"),
            "queryEndDate": end.strftime("%Y/%m/%d"),
        },
        headers=UA,
        timeout=60,
    )
    r.raise_for_status()
    text = r.content.decode("cp950", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if _pick(row, "契約") != "TX":
            continue
        out.append({
            "trade_date": (_pick(row, "交易日期") or "").replace("/", "-"),
            "session": _pick(row, "交易時段") or "",
            "month": (_pick(row, "到期月份") or "").strip(),
            "close": _num(_pick(row, "收盤價")),
            "chg": _num(_pick(row, "漲跌價")),
            "vol": _num(_pick(row, "成交量")),
        })
    if not out:
        raise RuntimeError("期交所 CSV 沒有 TX 資料（可能格式改變或尚未公布）")
    return out


def taifex_openapi() -> list[dict]:
    r = requests.get("https://openapi.taifex.com.tw/v1/DailyMarketReportFut", headers={**UA, "accept": "application/json"}, timeout=60)
    r.raise_for_status()
    out = []
    for row in r.json():
        if str(_pick(row, "contract")).strip() != "TX":
            continue
        d = str(_pick(row, "date") or "").strip()
        if len(d) == 8:
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        out.append({
            "trade_date": d,
            "session": str(_pick(row, "tradingsession", "session") or ""),
            "month": str(_pick(row, "contractmonth") or "").strip(),
            "close": _num(_pick(row, "last")),
            "chg": _num(_pick(row, "change")),
            "vol": _num(_pick(row, "volume")),
        })
    return out


def night_rows(raw: list[dict], known_days: set[str], same_day: bool = False) -> list[dict]:
    """把期交所資料轉成夜盤（起盤日）資料：近月（6 碼月份，非週選、非價差）。
    same_day=True 表示把交易日期直接當起盤日（備用對齊方式，由 update_txf 自動判斷）。"""
    day_dates = sorted({r["trade_date"] for r in raw if "一般" in r["session"]} | known_days)
    by_date: dict[str, list[dict]] = {}
    for r in raw:
        if "盤後" not in r["session"]:
            continue
        m = r["month"].replace(" ", "")
        if not (len(m) == 6 and m.isdigit()):
            continue
        if r["close"] is None:
            continue
        by_date.setdefault(r["trade_date"], []).append({**r, "month": m})
    out = []
    for t, rows in by_date.items():
        near = min(rows, key=lambda x: x["month"])
        prev = [d for d in day_dates if d < t]
        if same_day:
            start = t
        elif prev:
            start = prev[-1]
        else:  # 沒有營業日清單時，退回前一個平日
            dt = date.fromisoformat(t) - timedelta(days=1)
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
            start = dt.isoformat()
            warnings.append(f"txf {t} 夜盤起盤日以前一個平日 {start} 推定")
        out.append({
            "date": start,
            "close": int(round(near["close"])),
            "chg": None if near["chg"] is None else int(round(near["chg"])),
            "vol": None if near["vol"] is None else int(near["vol"]),
        })
    return out


def merge_txf(fresh: list[dict]) -> None:
    rows = load("txf")
    have = {r["date"]: r for r in rows}
    for f in fresh:
        old = have.get(f["date"])
        if old is None:
            if rows and f["date"] < rows[0]["date"]:
                continue
            rows.append(f)
            have[f["date"]] = f
            added["txf"].append(f["date"])
            continue
        if old.get("close") != f["close"] or (f["chg"] is not None and old.get("chg") != f["chg"]):
            warnings.append(f"txf {f['date']} 既有 {old.get('close')}/{old.get('chg')}，期交所 {f['close']}/{f['chg']}（未覆蓋）")
        if old.get("vol") is None and f["vol"] is not None and old.get("close") == f["close"]:
            old["vol"] = f["vol"]
            added["txf"].append(f"{f['date']}（補成交量）")
    save("txf", rows)


def update_txf() -> None:
    known = {r["date"] for r in load("txf")}
    today = datetime.now(TPE).date()
    raw: list[dict] = []
    try:
        raw = taifex_csv(today - timedelta(days=30), today)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"期交所 CSV 失敗，改用 OpenAPI：{e}")
        try:
            raw = taifex_openapi()
        except Exception as e2:  # noqa: BLE001
            warnings.append(f"期交所 OpenAPI 也失敗：{e2}")
            return
    # 自動確認日期對齊：用和既有資料的收盤價吻合筆數，決定「交易日期」要對到哪一個起盤日
    existing = {r["date"]: r["close"] for r in load("txf")}
    n_warn = len(warnings)
    a = night_rows(raw, known)
    b = night_rows(raw, known, same_day=True)
    del warnings[n_warn:]
    score = lambda rows: sum(1 for r in rows if existing.get(r["date"]) == r["close"])
    sa, sb = score(a), score(b)
    if sb > sa:
        warnings.append(f"txf 日期對齊採「交易日期＝起盤日」（吻合 {sb} 筆 vs {sa} 筆）")
        merge_txf(b)
    else:
        if sa == 0 and existing:
            warnings.append("txf 和既有資料沒有任何一筆收盤吻合，請人工確認期交所資料")
            return
        merge_txf(night_rows(raw, known))


def main() -> int:
    ok = 0
    for name, sym, tol in (("sox", "^SOX", 0.6), ("tsm", "TSM", 0.06)):
        try:
            merge_close(name, yahoo_daily(sym), tol)
            ok += 1
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{name} 失敗：{e}")
    update_txf()

    meta = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added": added,
        "warnings": warnings,
    }
    (DATA / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
