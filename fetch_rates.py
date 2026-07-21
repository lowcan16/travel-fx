#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import sys
import subprocess
from datetime import date

import certifi
import requests
import pandas as pd
from bs4 import BeautifulSoup

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

TRIP_START = date(2026, 7, 10)
TRIP_END   = date(2026, 7, 30)

REPO_DIR  = "/Users/kaiyingwei/travel-fx"
HTML_PATH = f"{REPO_DIR}/index.html"

CODE_MAP = {"JPY": "jpy", "USD": "usd", "CAD": "cad", "EUR": "eur", "GBP": "gbp",
            "HKD": "hkd", "AUD": "aud", "CNY": "cny"}
NAME_MAP = {"JPY": "日圓", "USD": "美元", "CAD": "加拿大幣", "EUR": "歐元", "GBP": "英鎊",
            "HKD": "港幣", "AUD": "澳幣", "CNY": "人民幣"}


def in_trip_window() -> bool:
    return TRIP_START <= date.today() <= TRIP_END


def get_boc_cash_rates():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36"
    }
    resp = requests.get("https://www.twrates.com/bankrate/bot.html", headers=headers, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    result = {}
    update_time = ""
    table = soup.find("table")
    for tr in table.find_all("tr")[1:]:
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cols) < 6:
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
        if not update_time:
            update_time = cols[5]
    return result, update_time


def get_card_rates(code: str) -> dict:
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


def update_html(new_data_js: str, cash_update_time: str) -> None:
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r"const DATA = \[.*?\];", lambda _: new_data_js, html, flags=re.S)
    if cash_update_time:
        html = re.sub(
            r'(id="cash-date">).*?(</b>)',
            lambda m: m.group(1) + cash_update_time + m.group(2),
            html,
        )
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)


def git_push():
    subprocess.run(["git", "-C", REPO_DIR, "add", "-A"], check=True)
    subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", f"更新匯率 {date.today()}"], check=False)
    subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)


def main():
    today = date.today()
    if not in_trip_window():
        print(f"{today} 不在旅行區間（{TRIP_START} ~ {TRIP_END}）內，今天跳過，不做任何事。")
        sys.exit(0)

    print(f"{today} 在旅行區間內，開始抓匯率...")
    cash, cash_update_time = get_boc_cash_rates()
    cards = {code: get_card_rates(code) for code in CODE_MAP}
    new_data_js = build_data_js(cash, cards)
    update_html(new_data_js, cash_update_time)
    git_push()
    print(f"完成，已更新 {HTML_PATH}，更新時間標記：{cash_update_time}")


if __name__ == "__main__":
    main()
