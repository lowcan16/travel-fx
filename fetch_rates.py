#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_rates.py
只在「旅行期間」內抓當天匯率（現金 + VISA + Mastercard），
自動更新「出國匯率換算.html」裡的資料。

用法：
  1. 改下面 TRIP_START / TRIP_END / HTML_PATH 三個設定
  2. 排 cron 每天固定時間執行一次（例如每天早上 8:00）
     crontab -e 加入：
     0 8 * * * /usr/bin/python3 /完整路徑/fetch_rates.py >> /完整路徑/fetch_rates.log 2>&1
  3. 不在旅行區間內的日子，程式會直接印訊息、什麼都不改，不需要另外移除 cron

需要先安裝套件：
  pip3 install requests beautifulsoup4 lxml pandas
"""

import os
import re
import sys
from datetime import date

import certifi
import requests
import pandas as pd
from bs4 import BeautifulSoup

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# ── 1. 改成你的實際旅行日期（含頭尾兩天）──────────────────────
TRIP_START = date(2026, 7, 10)
TRIP_END   = date(2026, 7, 30)

# ── 2. 改成 出國匯率換算.html 在你 Mac 上的實際路徑 ──────────────
HTML_PATH = "/Users/kaiyingwei/Library/Mobile Documents/com~apple~CloudDocs/fetch_rate/出國匯率換算.html"

# ── 幣別對照表：JS 檔裡的順序就是這個順序，不要隨便調動 ──────────
CODE_MAP = {"JPY": "jpy", "USD": "usd", "EUR": "eur", "GBP": "gbp",
            "HKD": "hkd", "AUD": "aud", "CNY": "cny"}
NAME_MAP = {"JPY": "日圓", "USD": "美元", "EUR": "歐元", "GBP": "英鎊",
            "HKD": "港幣", "AUD": "澳幣", "CNY": "人民幣"}


def in_trip_window() -> bool:
    """今天是不是在旅行區間內（含頭尾）。"""
    return TRIP_START <= date.today() <= TRIP_END


def get_boc_cash_rates() -> dict:
    """抓臺灣銀行牌告匯率（透過 twrates.com，同一個網站不會擋爬蟲）。
    回傳 {幣別: {現金買入, 現金賣出, 即期買入, 即期賣出}}。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36"
    }
    resp = requests.get("https://www.twrates.com/bankrate/bot.html", headers=headers, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    result = {}
    table = soup.find("table")
    for tr in table.find_all("tr")[1:]:
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cols) < 5:
            continue
        m = re.match(r".*\((\w+)\)", cols[0])
        if not m:
            continue
        code = m.group(1)

        def to_float(s):
            return float(s) if s not in ("--", "", "-") else None

        result[code] = {
            "即期買入": to_float(cols[1]),
            "即期賣出": to_float(cols[2]),
            "現金買入": to_float(cols[3]),
            "現金賣出": to_float(cols[4]),
        }
    return result


def get_card_rates(code: str) -> dict:
    """抓 twrates.com 上某幣別的 VISA / 萬事達 / JCB 匯率比較表。"""
    url = f"https://www.twrates.com/card/visa/{CODE_MAP[code]}.html"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    result = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cols = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cols) < 2:
                continue
            card_name, rate_cell = cols[0], cols[1]
            m = re.match(r"([\d.]+)\s*\(([\d/-]+)\)", rate_cell)
            if card_name in ("VISA", "萬事達") and m:
                result[card_name] = {"rate": float(m.group(1)), "date": m.group(2)}
    return result


def build_data_js(cash: dict, cards: dict) -> str:
    """組出新的 `const DATA = [...]` JS 區塊。"""
    lines = ["const DATA = ["]
    for code in CODE_MAP:
        c = cash.get(code)
        card = cards.get(code, {})
        visa = card.get("VISA")
        mc = card.get("萬事達")
        if not c or not visa or not mc:
            print(f"⚠️  {code} 資料抓不完整，本次跳過更新這個幣別，維持舊資料。")
            continue
        lines.append(
            "  { code:'%s', name:'%s', cashBuy:%s, cashSell:%s, "
            "visa:%s, visaDate:'%s', mc:%s, mcDate:'%s' },"
            % (code, NAME_MAP[code], c["現金買入"], c["現金賣出"],
               visa["rate"], visa["date"][5:], mc["rate"], mc["date"][5:])
        )
    lines.append("];")
    return "\n".join(lines)


def update_html(new_data_js: str) -> None:
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    new_html = re.sub(r"const DATA = \[.*?\];", lambda _: new_data_js, html, flags=re.S)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)


def main():
    today = date.today()
    if not in_trip_window():
        print(f"{today} 不在旅行區間（{TRIP_START} ~ {TRIP_END}）內，今天跳過，不做任何事。")
        sys.exit(0)

    print(f"{today} 在旅行區間內，開始抓匯率...")
    cash = get_boc_cash_rates()
    cards = {code: get_card_rates(code) for code in CODE_MAP}
    new_data_js = build_data_js(cash, cards)
    update_html(new_data_js)
    print(f"完成，已更新 {HTML_PATH}")


if __name__ == "__main__":
    main()
