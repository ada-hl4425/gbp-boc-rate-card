#!/usr/bin/env python3
"""
多银行英镑汇率抓取脚本
支持银行：中国银行、工商银行、建设银行、招商银行、交通银行、农业银行
- 优先使用 API 接口，更可靠
- 并行获取所有银行汇率
- 自动找出最优汇率
"""

import json
import sys
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: BeautifulSoup not installed. Run: pip install beautifulsoup4")
    sys.exit(1)


MAX_RETRIES = 3
RETRY_DELAY = 3
VALID_RATE_RANGE = (5.0, 15.0)  # 合理汇率范围 CNY per GBP

# 银行配置
BANKS = {
    "BOC": {
        "name": "中国银行",
        "short_name": "中行",
        "color": "#e60012"
    },
    "ICBC": {
        "name": "中国工商银行",
        "short_name": "工行",
        "color": "#c4161c"
    },
    "CCB": {
        "name": "中国建设银行",
        "short_name": "建行",
        "color": "#004098"
    },
    "CMB": {
        "name": "招商银行",
        "short_name": "招行",
        "color": "#c41230"
    },
    "BOCOM": {
        "name": "交通银行",
        "short_name": "交行",
        "color": "#004a8f"
    },
    "ABC": {
        "name": "中国农业银行",
        "short_name": "农行",
        "color": "#007f4e"
    }
}


def fetch_url(url: str, headers: Dict = None, retries: int = MAX_RETRIES) -> bytes:
    """带重试机制的 URL 获取"""
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)

    for attempt in range(retries):
        try:
            req = Request(url, headers=default_headers)
            with urlopen(req, timeout=30) as resp:
                return resp.read()
        except (URLError, HTTPError) as e:
            print(f"  Attempt {attempt + 1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise
    return b""


def validate_rate(rate: float, bank_code: str) -> bool:
    """验证汇率是否在合理范围内"""
    if not (VALID_RATE_RANGE[0] <= rate <= VALID_RATE_RANGE[1]):
        print(f"  Warning: {bank_code} rate {rate} is outside valid range {VALID_RATE_RANGE}")
        return False
    return True


def make_result(bank_code: str, rate: float, source_url: str, publish_time: str = "") -> Dict:
    """构建统一的返回结果"""
    return {
        "bank_code": bank_code,
        "bank_name": BANKS[bank_code]["name"],
        "short_name": BANKS[bank_code]["short_name"],
        "rate": round(rate, 4),
        "rate_type": "现汇卖出价",
        "publish_time": publish_time,
        "source_url": source_url,
        "color": BANKS[bank_code]["color"],
        "status": "success"
    }


# ==================== 各银行解析函数 ====================

def fetch_boc() -> Optional[Dict]:
    """中国银行 - 官网HTML解析"""
    bank_code = "BOC"
    url = "https://www.boc.cn/sourcedb/whpj/"
    print(f"Fetching {bank_code}...")

    try:
        content = fetch_url(url)
        html = content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, 'html.parser')

        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 7:
                continue

            cell_texts = [cell.get_text(strip=True) for cell in cells]
            if '英镑' not in cell_texts[0] and 'GBP' not in cell_texts[0]:
                continue

            # 中行格式：货币名称 | 现汇买入价 | 现钞买入价 | 现汇卖出价 | 现钞卖出价 | 中行折算价 | 发布时间
            rate_per_100 = float(cell_texts[3].replace(',', ''))
            rate = rate_per_100 / 100.0
            publish_time = cell_texts[6] if len(cell_texts) > 6 else ""

            if validate_rate(rate, bank_code):
                return make_result(bank_code, rate, url, publish_time)

        raise RuntimeError("Could not find GBP rate in BOC page")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return None


def fetch_icbc() -> Optional[Dict]:
    """工商银行 - API接口"""
    bank_code = "ICBC"
    # 工商银行外汇牌价 API
    url = "https://papi.icbc.com.cn/exchanges/quotation?currencyCode=13"  # 13 = GBP
    print(f"Fetching {bank_code}...")

    try:
        headers = {
            "Accept": "application/json",
            "Referer": "https://icbc.com.cn/"
        }
        content = fetch_url(url, headers)
        data = json.loads(content.decode('utf-8'))

        # API 返回格式：{"quotation": {"reference": "xxx", "sellPrice": "954.44", ...}}
        if 'quotation' in data:
            sell_price = data['quotation'].get('sellPrice') or data['quotation'].get('sellprice')
            if sell_price:
                rate = float(sell_price) / 100.0
                if validate_rate(rate, bank_code):
                    return make_result(bank_code, rate, "https://icbc.com.cn")

        raise RuntimeError("Invalid API response")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        # 备用方案：HTML解析
        return fetch_icbc_html()


def fetch_icbc_html() -> Optional[Dict]:
    """工商银行 - HTML备用方案"""
    bank_code = "ICBC"
    url = "https://icbc.com.cn/column/1438058341489590354.html"

    try:
        content = fetch_url(url)
        html = content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, 'html.parser')

        for row in soup.find_all('tr'):
            text = row.get_text()
            if '英镑' in text or 'GBP' in text:
                # 查找数值
                numbers = re.findall(r'\d+\.\d+', text)
                for num_str in numbers:
                    val = float(num_str)
                    if 500 < val < 1500:
                        rate = val / 100.0
                        if validate_rate(rate, bank_code):
                            return make_result(bank_code, rate, url)

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error in ICBC HTML fallback: {e}")
        return None


def fetch_ccb() -> Optional[Dict]:
    """建设银行 - API接口"""
    bank_code = "CCB"
    # 建设银行外汇牌价 API
    url = "https://forex.ccb.com/cn/forex/quotation/quotation.xml"
    print(f"Fetching {bank_code}...")

    try:
        content = fetch_url(url)
        text = content.decode('utf-8', errors='ignore')

        # XML 格式解析
        # 查找英镑的卖出价
        gbp_match = re.search(r'<Currency>GBP</Currency>.*?<SE_BID>(\d+\.?\d*)</SE_BID>', text, re.DOTALL)
        if gbp_match:
            rate_per_100 = float(gbp_match.group(1))
            rate = rate_per_100 / 100.0
            if validate_rate(rate, bank_code):
                return make_result(bank_code, rate, "https://forex.ccb.com")

        # 备用：查找英镑相关数值
        if '英镑' in text or 'GBP' in text:
            numbers = re.findall(r'>(\d{3}\.\d+)<', text)
            for num_str in numbers:
                val = float(num_str)
                if 500 < val < 1500:
                    rate = val / 100.0
                    if validate_rate(rate, bank_code):
                        return make_result(bank_code, rate, "https://forex.ccb.com")

        raise RuntimeError("Could not find GBP rate in CCB API")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return None


def fetch_cmb() -> Optional[Dict]:
    """招商银行 - API接口"""
    bank_code = "CMB"
    # 招商银行外汇牌价 API
    url = "https://fx.cmbchina.com/api/v1/fx/rate"
    print(f"Fetching {bank_code}...")

    try:
        headers = {
            "Accept": "application/json",
            "Referer": "https://www.cmbchina.com/"
        }
        content = fetch_url(url, headers)
        data = json.loads(content.decode('utf-8'))

        # 查找英镑
        rates = data.get('data', data.get('body', []))
        if isinstance(rates, list):
            for item in rates:
                currency = item.get('currency', item.get('currencyCode', ''))
                if 'GBP' in currency or '英镑' in currency:
                    sell = item.get('sellPrice', item.get('sell', item.get('SE_BID')))
                    if sell:
                        rate = float(sell) / 100.0
                        if validate_rate(rate, bank_code):
                            return make_result(bank_code, rate, "https://www.cmbchina.com")

        raise RuntimeError("Could not find GBP rate in CMB API")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return fetch_cmb_html()


def fetch_cmb_html() -> Optional[Dict]:
    """招商银行 - HTML备用方案"""
    bank_code = "CMB"
    url = "https://www.cmbchina.com/CmbWebPubInfo/RateResult.aspx?chnl=whjjckll"

    try:
        content = fetch_url(url)
        html = content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, 'html.parser')

        for row in soup.find_all('tr'):
            text = row.get_text()
            if '英镑' in text or 'GBP' in text:
                numbers = re.findall(r'\d+\.\d+', text)
                for num_str in numbers:
                    val = float(num_str)
                    if 500 < val < 1500:
                        rate = val / 100.0
                        if validate_rate(rate, bank_code):
                            return make_result(bank_code, rate, url)

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error in CMB HTML fallback: {e}")
        return None


def fetch_bocom() -> Optional[Dict]:
    """交通银行 - API/HTML"""
    bank_code = "BOCOM"
    url = "https://www.bankcomm.com/BankCommSite/zonghang/cn/whpj/rmbwhpj/index.html"
    print(f"Fetching {bank_code}...")

    try:
        content = fetch_url(url)
        html = content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, 'html.parser')

        # 查找表格数据
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            row_text = row.get_text()
            if '英镑' in row_text or 'GBP' in row_text:
                for cell in cells:
                    text = cell.get_text(strip=True).replace(',', '')
                    try:
                        val = float(text)
                        if 500 < val < 1500:
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                return make_result(bank_code, rate, url)
                    except ValueError:
                        continue

        # 尝试从脚本中提取数据
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and ('英镑' in script.string or 'GBP' in script.string):
                numbers = re.findall(r'(\d{3}\.\d+)', script.string)
                for num_str in numbers:
                    val = float(num_str)
                    if 500 < val < 1500:
                        rate = val / 100.0
                        if validate_rate(rate, bank_code):
                            return make_result(bank_code, rate, url)

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return None


def fetch_abc() -> Optional[Dict]:
    """农业银行 - API/HTML"""
    bank_code = "ABC"
    # 农行外汇牌价页面
    url = "https://ewealth.abchina.com/app/data/api/DataService/ExchangeRateV2"
    print(f"Fetching {bank_code}...")

    try:
        # 尝试 API
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": "https://www.abchina.com/"
        }
        content = fetch_url(url, headers)
        data = json.loads(content.decode('utf-8'))

        rates = data.get('Data', data.get('data', []))
        if isinstance(rates, list):
            for item in rates:
                currency = str(item.get('CurrencyName', item.get('Currency', '')))
                if '英镑' in currency or 'GBP' in currency:
                    sell = item.get('SellPrice', item.get('SE_BID'))
                    if sell:
                        rate = float(sell) / 100.0
                        if validate_rate(rate, bank_code):
                            return make_result(bank_code, rate, "https://www.abchina.com")

        raise RuntimeError("Could not find GBP rate in ABC API")
    except Exception as e:
        print(f"  Error fetching {bank_code} API: {e}")
        return fetch_abc_html()


def fetch_abc_html() -> Optional[Dict]:
    """农业银行 - HTML备用方案"""
    bank_code = "ABC"
    url = "https://www.abchina.com/cn/ForeignExchange/"

    try:
        content = fetch_url(url)
        html = content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, 'html.parser')

        for row in soup.find_all('tr'):
            text = row.get_text()
            if '英镑' in text or 'GBP' in text:
                numbers = re.findall(r'\d+\.\d+', text)
                for num_str in numbers:
                    val = float(num_str)
                    if 500 < val < 1500:
                        rate = val / 100.0
                        if validate_rate(rate, bank_code):
                            return make_result(bank_code, rate, url)

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error in ABC HTML fallback: {e}")
        return None


# 银行获取函数映射
FETCH_FUNCTIONS = {
    "BOC": fetch_boc,
    "ICBC": fetch_icbc,
    "CCB": fetch_ccb,
    "CMB": fetch_cmb,
    "BOCOM": fetch_bocom,
    "ABC": fetch_abc
}


def fetch_all_banks() -> List[Dict]:
    """并行获取所有银行汇率"""
    results = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_bank = {
            executor.submit(func): bank_code
            for bank_code, func in FETCH_FUNCTIONS.items()
        }

        for future in as_completed(future_to_bank):
            bank_code = future_to_bank[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                    print(f"  ✓ {bank_code}: {result['rate']} CNY/GBP")
                else:
                    print(f"  ✗ {bank_code}: Failed to fetch")
            except Exception as e:
                print(f"  ✗ {bank_code}: Exception - {e}")

    return results


def find_best_rate(banks: List[Dict]) -> Optional[Dict]:
    """找出最优汇率（最低的卖出价）"""
    if not banks:
        return None
    return min(banks, key=lambda x: x['rate'])


def load_previous_data(filepath: Path) -> Optional[Dict]:
    """加载上一次的数据"""
    try:
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load previous data: {e}")
    return None


def calculate_changes(current_banks: List[Dict], previous_data: Optional[Dict]) -> List[Dict]:
    """计算汇率变化"""
    if not previous_data or 'banks' not in previous_data:
        return current_banks

    prev_banks = {b['bank_code']: b for b in previous_data.get('banks', [])}

    for bank in current_banks:
        code = bank['bank_code']
        if code in prev_banks:
            old_rate = prev_banks[code].get('rate', 0)
            new_rate = bank['rate']
            if old_rate > 0:
                change = new_rate - old_rate
                bank['rate_change'] = round(change, 4)
                bank['rate_change_percent'] = round((change / old_rate) * 100, 2)

    return current_banks


def save_data(data: Dict, filepath: Path):
    """保存数据"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✓ Saved data to {filepath}")


def main():
    output_path = Path("docs/data.json")

    print(f"Starting multi-bank GBP rate fetch at {datetime.now().isoformat()}")
    print("=" * 60)

    try:
        previous_data = load_previous_data(output_path)

        print("\nFetching rates from all banks...")
        banks = fetch_all_banks()

        if not banks:
            raise RuntimeError("Failed to fetch any bank rates")

        banks = calculate_changes(banks, previous_data)
        banks.sort(key=lambda x: x['rate'])
        best = find_best_rate(banks)

        now = datetime.now(timezone.utc)
        data = {
            "currency": "英镑",
            "pair": "GBP/CNY",
            "rate_type": "现汇卖出价",
            "best_bank": best['bank_code'] if best else None,
            "best_rate": best['rate'] if best else None,
            "banks": banks,
            "bank_count": len(banks),
            "fetched_at_utc": now.isoformat(),
            "fetched_at_beijing": now.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "success"
        }

        save_data(data, output_path)

        print("\n" + "=" * 60)
        print(f"Summary: {len(banks)} banks fetched")
        if best:
            print(f"Best rate: {best['short_name']} - {best['rate']} CNY/GBP")
        for b in banks:
            change_str = ""
            if 'rate_change' in b:
                arrow = "↑" if b['rate_change'] > 0 else "↓" if b['rate_change'] < 0 else "→"
                change_str = f" ({arrow}{abs(b['rate_change']):.4f})"
            print(f"  {b['short_name']}: {b['rate']}{change_str}")

        print("\n✓ Task completed successfully")
        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Fatal error: {e}", file=sys.stderr)

        if not output_path.exists():
            error_data = {
                "status": "error",
                "error_message": str(e),
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "banks": []
            }
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(error_data, f, ensure_ascii=False, indent=2)
            except:
                pass

        sys.exit(1)


if __name__ == "__main__":
    main()
