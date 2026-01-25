#!/usr/bin/env python3
"""
多银行英镑汇率抓取脚本
支持银行：中国银行、工商银行、建设银行、招商银行、交通银行、农业银行
使用各银行官方外汇牌价页面
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
        "url": "https://www.boc.cn/sourcedb/whpj/",
        "color": "#e60012"
    },
    "ICBC": {
        "name": "中国工商银行",
        "short_name": "工行",
        "url": "https://www.icbc.com.cn/column/1438058341489590354.html",
        "color": "#c4161c"
    },
    "CCB": {
        "name": "中国建设银行",
        "short_name": "建行",
        "url": "https://www2.ccb.com/chn/forex/exchange-quotations.shtml",
        "color": "#004098"
    },
    "CMB": {
        "name": "招商银行",
        "short_name": "招行",
        "url": "https://fx.cmbchina.com/hq/",
        "color": "#c41230"
    },
    "BOCOM": {
        "name": "交通银行",
        "short_name": "交行",
        "url": "https://www.bankcomm.com/BankCommSite/shtml/jyjr/cn/7158/7161/8091/list.shtml",
        "color": "#004a8f"
    },
    "ABC": {
        "name": "中国农业银行",
        "short_name": "农行",
        "url": "https://ewealth.abchina.com/foreignexchange/listprice/",
        "color": "#007f4e"
    }
}


def fetch_url(url: str, headers: Dict = None, retries: int = MAX_RETRIES) -> bytes:
    """带重试机制的 URL 获取"""
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    if headers:
        default_headers.update(headers)

    for attempt in range(retries):
        try:
            req = Request(url, headers=default_headers)
            with urlopen(req, timeout=30) as resp:
                return resp.read()
        except (URLError, HTTPError) as e:
            print(f"  Attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise
    return b""


def decode_content(content: bytes) -> str:
    """尝试多种编码解码"""
    for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode('utf-8', errors='ignore')


def validate_rate(rate: float, bank_code: str) -> bool:
    """验证汇率是否在合理范围内"""
    if not (VALID_RATE_RANGE[0] <= rate <= VALID_RATE_RANGE[1]):
        print(f"  Warning: {bank_code} rate {rate} outside valid range")
        return False
    return True


def make_result(bank_code: str, rate: float, publish_time: str = "") -> Dict:
    """构建统一的返回结果"""
    return {
        "bank_code": bank_code,
        "bank_name": BANKS[bank_code]["name"],
        "short_name": BANKS[bank_code]["short_name"],
        "rate": round(rate, 4),
        "rate_type": "现汇卖出价",
        "publish_time": publish_time,
        "source_url": BANKS[bank_code]["url"],
        "color": BANKS[bank_code]["color"],
        "status": "success"
    }


def extract_gbp_rate(text: str, bank_code: str) -> Optional[float]:
    """从文本中提取英镑汇率"""
    # 查找所有可能的数值（格式：9xx.xx 或 9.xxxx）
    numbers = re.findall(r'(\d{3,4}\.?\d*)', text)
    for num_str in numbers:
        try:
            val = float(num_str)
            # 判断是否是 100外币 = xxx人民币 的格式
            if 500 < val < 1500:
                rate = val / 100.0
                if validate_rate(rate, bank_code):
                    return rate
            # 或者直接是汇率格式
            elif 5 < val < 15:
                if validate_rate(val, bank_code):
                    return val
        except ValueError:
            continue
    return None


# ==================== 各银行解析函数 ====================

def fetch_boc() -> Optional[Dict]:
    """中国银行 - https://www.boc.cn/sourcedb/whpj/"""
    bank_code = "BOC"
    url = BANKS[bank_code]["url"]
    print(f"Fetching {bank_code} from {url}")

    try:
        content = fetch_url(url)
        html = decode_content(content)
        soup = BeautifulSoup(html, 'html.parser')

        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 7:
                continue

            cell_texts = [cell.get_text(strip=True) for cell in cells]
            if '英镑' not in cell_texts[0] and 'GBP' not in cell_texts[0]:
                continue

            # 中行格式：货币名称 | 现汇买入价 | 现钞买入价 | 现汇卖出价 | 现钞卖出价 | 中行折算价 | 发布时间
            rate_str = cell_texts[3].replace(',', '')
            rate_per_100 = float(rate_str)
            rate = rate_per_100 / 100.0
            publish_time = cell_texts[6] if len(cell_texts) > 6 else ""

            if validate_rate(rate, bank_code):
                print(f"  ✓ {bank_code}: {rate}")
                return make_result(bank_code, rate, publish_time)

        raise RuntimeError("GBP not found")
    except Exception as e:
        print(f"  ✗ {bank_code}: {e}")
        return None


def fetch_icbc() -> Optional[Dict]:
    """工商银行 - https://www.icbc.com.cn/column/1438058341489590354.html"""
    bank_code = "ICBC"
    url = BANKS[bank_code]["url"]
    print(f"Fetching {bank_code} from {url}")

    try:
        content = fetch_url(url)
        html = decode_content(content)
        soup = BeautifulSoup(html, 'html.parser')

        # 工行页面使用表格展示
        for row in soup.find_all('tr'):
            row_text = row.get_text()
            if '英镑' in row_text or 'GBP' in row_text:
                cells = row.find_all('td')
                if len(cells) >= 5:
                    # 工行格式通常是：币种 | 现汇买入 | 现钞买入 | 现汇卖出 | 现钞卖出
                    for i, cell in enumerate(cells):
                        text = cell.get_text(strip=True).replace(',', '')
                        try:
                            val = float(text)
                            if 500 < val < 1500:
                                rate = val / 100.0
                                if validate_rate(rate, bank_code):
                                    print(f"  ✓ {bank_code}: {rate}")
                                    return make_result(bank_code, rate)
                        except ValueError:
                            continue

        raise RuntimeError("GBP not found")
    except Exception as e:
        print(f"  ✗ {bank_code}: {e}")
        return None


def fetch_ccb() -> Optional[Dict]:
    """建设银行 - https://www2.ccb.com/chn/forex/exchange-quotations.shtml"""
    bank_code = "CCB"
    url = BANKS[bank_code]["url"]
    print(f"Fetching {bank_code} from {url}")

    try:
        content = fetch_url(url)
        html = decode_content(content)
        soup = BeautifulSoup(html, 'html.parser')

        # 建行页面查找英镑行
        for row in soup.find_all('tr'):
            row_text = row.get_text()
            if '英镑' in row_text or 'GBP' in row_text:
                cells = row.find_all('td')
                for cell in cells:
                    text = cell.get_text(strip=True).replace(',', '')
                    try:
                        val = float(text)
                        if 500 < val < 1500:
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                print(f"  ✓ {bank_code}: {rate}")
                                return make_result(bank_code, rate)
                    except ValueError:
                        continue

        # 备用：尝试从整个页面提取
        if '英镑' in html or 'GBP' in html:
            rate = extract_gbp_rate(html, bank_code)
            if rate:
                print(f"  ✓ {bank_code}: {rate}")
                return make_result(bank_code, rate)

        raise RuntimeError("GBP not found")
    except Exception as e:
        print(f"  ✗ {bank_code}: {e}")
        return None


def fetch_cmb() -> Optional[Dict]:
    """招商银行 - https://fx.cmbchina.com/hq/"""
    bank_code = "CMB"
    url = BANKS[bank_code]["url"]
    print(f"Fetching {bank_code} from {url}")

    try:
        content = fetch_url(url)
        html = decode_content(content)
        soup = BeautifulSoup(html, 'html.parser')

        # 招行页面查找英镑
        for row in soup.find_all('tr'):
            row_text = row.get_text()
            if '英镑' in row_text or 'GBP' in row_text:
                cells = row.find_all('td')
                for cell in cells:
                    text = cell.get_text(strip=True).replace(',', '')
                    try:
                        val = float(text)
                        if 500 < val < 1500:
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                print(f"  ✓ {bank_code}: {rate}")
                                return make_result(bank_code, rate)
                    except ValueError:
                        continue

        # 备用方案
        if '英镑' in html or 'GBP' in html:
            rate = extract_gbp_rate(html, bank_code)
            if rate:
                print(f"  ✓ {bank_code}: {rate}")
                return make_result(bank_code, rate)

        raise RuntimeError("GBP not found")
    except Exception as e:
        print(f"  ✗ {bank_code}: {e}")
        return None


def fetch_bocom() -> Optional[Dict]:
    """交通银行 - https://www.bankcomm.com/BankCommSite/shtml/jyjr/cn/7158/7161/8091/list.shtml"""
    bank_code = "BOCOM"
    url = BANKS[bank_code]["url"]
    print(f"Fetching {bank_code} from {url}")

    try:
        content = fetch_url(url)
        html = decode_content(content)
        soup = BeautifulSoup(html, 'html.parser')

        # 交行页面查找英镑
        for row in soup.find_all('tr'):
            row_text = row.get_text()
            if '英镑' in row_text or 'GBP' in row_text:
                cells = row.find_all('td')
                for cell in cells:
                    text = cell.get_text(strip=True).replace(',', '')
                    try:
                        val = float(text)
                        if 500 < val < 1500:
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                print(f"  ✓ {bank_code}: {rate}")
                                return make_result(bank_code, rate)
                    except ValueError:
                        continue

        # 备用
        if '英镑' in html or 'GBP' in html:
            rate = extract_gbp_rate(html, bank_code)
            if rate:
                print(f"  ✓ {bank_code}: {rate}")
                return make_result(bank_code, rate)

        raise RuntimeError("GBP not found")
    except Exception as e:
        print(f"  ✗ {bank_code}: {e}")
        return None


def fetch_abc() -> Optional[Dict]:
    """农业银行 - https://ewealth.abchina.com/foreignexchange/listprice/"""
    bank_code = "ABC"
    url = BANKS[bank_code]["url"]
    print(f"Fetching {bank_code} from {url}")

    try:
        content = fetch_url(url)
        html = decode_content(content)
        soup = BeautifulSoup(html, 'html.parser')

        # 农行页面查找英镑
        for row in soup.find_all('tr'):
            row_text = row.get_text()
            if '英镑' in row_text or 'GBP' in row_text:
                cells = row.find_all('td')
                for cell in cells:
                    text = cell.get_text(strip=True).replace(',', '')
                    try:
                        val = float(text)
                        if 500 < val < 1500:
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                print(f"  ✓ {bank_code}: {rate}")
                                return make_result(bank_code, rate)
                    except ValueError:
                        continue

        # 备用
        if '英镑' in html or 'GBP' in html:
            rate = extract_gbp_rate(html, bank_code)
            if rate:
                print(f"  ✓ {bank_code}: {rate}")
                return make_result(bank_code, rate)

        raise RuntimeError("GBP not found")
    except Exception as e:
        print(f"  ✗ {bank_code}: {e}")
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
            except Exception as e:
                print(f"  ✗ {bank_code}: Exception - {e}")

    return results


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
    print(f"✓ Saved to {filepath}")


def main():
    output_path = Path("docs/data.json")

    print(f"Multi-bank GBP rate fetch - {datetime.now().isoformat()}")
    print("=" * 60)

    try:
        previous_data = load_previous_data(output_path)

        print("\nFetching from all banks...")
        banks = fetch_all_banks()

        print(f"\nFetched {len(banks)} banks successfully")

        if not banks:
            raise RuntimeError("Failed to fetch any bank rates")

        banks = calculate_changes(banks, previous_data)
        banks.sort(key=lambda x: x['rate'])
        best = min(banks, key=lambda x: x['rate']) if banks else None

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
        print(f"Summary: {len(banks)}/6 banks")
        if best:
            print(f"Best: {best['short_name']} = {best['rate']} CNY/GBP")
        for b in banks:
            change = ""
            if 'rate_change' in b:
                arrow = "↑" if b['rate_change'] > 0 else "↓" if b['rate_change'] < 0 else "→"
                change = f" ({arrow}{abs(b['rate_change']):.4f})"
            print(f"  {b['short_name']}: {b['rate']}{change}")

        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
