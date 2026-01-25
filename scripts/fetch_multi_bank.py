#!/usr/bin/env python3
"""
多银行英镑汇率抓取脚本
支持银行：中国银行、工商银行、建设银行、招商银行、交通银行、农业银行
- 并行获取所有银行汇率
- 自动找出最优汇率
- 完整错误处理和重试机制
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
RETRY_DELAY = 5
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
        "url": "https://mybank.icbc.com.cn/icbc/newperbank/perbank3/frame/frame_index.jsp",
        "api_url": "https://papi.icbc.com.cn/exchanges/quotation?currencyCode=GBP",
        "color": "#c4161c"
    },
    "CCB": {
        "name": "中国建设银行",
        "short_name": "建行",
        "url": "http://forex.ccb.com/cn/forex/exchange-quotations.html",
        "color": "#004098"
    },
    "CMB": {
        "name": "招商银行",
        "short_name": "招行",
        "url": "https://www.cmbchina.com/CmbWebPubInfo/RateResult.aspx?chnl=whjjckll",
        "color": "#c41230"
    },
    "BOCOM": {
        "name": "交通银行",
        "short_name": "交行",
        "url": "https://www.bankcomm.com/BankCommSite/zonghang/cn/whpj/rmbwhpj/index.html",
        "color": "#004a8f"
    },
    "ABC": {
        "name": "中国农业银行",
        "short_name": "农行",
        "url": "https://www.abchina.com/cn/ForeignExchange/",
        "color": "#007f4e"
    }
}


def fetch_html_with_retry(url: str, retries: int = MAX_RETRIES, encoding: str = "utf-8") -> str:
    """带重试机制的 HTML 获取"""
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            with urlopen(req, timeout=30) as resp:
                content = resp.read()
                # 尝试多种编码
                for enc in [encoding, 'utf-8', 'gbk', 'gb2312']:
                    try:
                        return content.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return content.decode('utf-8', errors='ignore')
        except (URLError, HTTPError) as e:
            print(f"  Attempt {attempt + 1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(f"Failed to fetch {url} after {retries} attempts") from e
    return ""


def fetch_json_with_retry(url: str, retries: int = MAX_RETRIES) -> Dict:
    """带重试机制的 JSON 获取"""
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
            })
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            print(f"  Attempt {attempt + 1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(f"Failed to fetch {url} after {retries} attempts") from e
    return {}


def validate_rate(rate: float, bank_code: str) -> bool:
    """验证汇率是否在合理范围内"""
    if not (VALID_RATE_RANGE[0] <= rate <= VALID_RATE_RANGE[1]):
        print(f"  Warning: {bank_code} rate {rate} is outside valid range {VALID_RATE_RANGE}")
        return False
    return True


# ==================== 各银行解析函数 ====================

def fetch_boc() -> Optional[Dict]:
    """中国银行 - 从官网HTML解析"""
    bank_code = "BOC"
    print(f"Fetching {bank_code}...")
    try:
        html = fetch_html_with_retry(BANKS[bank_code]["url"])
        soup = BeautifulSoup(html, 'html.parser')

        rows = soup.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 7:
                continue

            cell_texts = [cell.get_text(strip=True) for cell in cells]
            currency_name = cell_texts[0]

            if '英镑' not in currency_name and 'GBP' not in currency_name:
                continue

            # 中行格式：货币名称 | 现汇买入价 | 现钞买入价 | 现汇卖出价 | 现钞卖出价 | 中行折算价 | 发布时间
            cash_selling_str = cell_texts[3].replace(',', '')
            publish_time = cell_texts[6]

            rate_per_100 = float(cash_selling_str)
            rate = rate_per_100 / 100.0

            if not validate_rate(rate, bank_code):
                return None

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

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return None


def fetch_icbc() -> Optional[Dict]:
    """工商银行 - 从官网HTML解析"""
    bank_code = "ICBC"
    print(f"Fetching {bank_code}...")
    try:
        # 工商银行外汇牌价页面
        url = "https://icbc.com.cn/column/1438058341489590354.html"
        html = fetch_html_with_retry(url)
        soup = BeautifulSoup(html, 'html.parser')

        # 查找包含英镑的行
        rows = soup.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 5:
                continue

            cell_texts = [cell.get_text(strip=True) for cell in cells]
            row_text = ' '.join(cell_texts).lower()

            if '英镑' in row_text or 'gbp' in row_text:
                # 找到现汇卖出价（通常是第4或第5列）
                for i, text in enumerate(cell_texts):
                    try:
                        val = float(text.replace(',', ''))
                        if 500 < val < 1500:  # 100外币对应的人民币
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                return {
                                    "bank_code": bank_code,
                                    "bank_name": BANKS[bank_code]["name"],
                                    "short_name": BANKS[bank_code]["short_name"],
                                    "rate": round(rate, 4),
                                    "rate_type": "现汇卖出价",
                                    "publish_time": "",
                                    "source_url": url,
                                    "color": BANKS[bank_code]["color"],
                                    "status": "success"
                                }
                    except ValueError:
                        continue

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return None


def fetch_ccb() -> Optional[Dict]:
    """建设银行 - 从官网HTML解析"""
    bank_code = "CCB"
    print(f"Fetching {bank_code}...")
    try:
        url = "http://forex.ccb.com/cn/forex/exchange-quotations.html"
        html = fetch_html_with_retry(url, encoding='utf-8')
        soup = BeautifulSoup(html, 'html.parser')

        # 查找表格中的英镑行
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 5:
                    continue

                cell_texts = [cell.get_text(strip=True) for cell in cells]
                row_text = ' '.join(cell_texts)

                if '英镑' in row_text or 'GBP' in row_text:
                    # 尝试提取数值
                    for text in cell_texts:
                        try:
                            val = float(text.replace(',', ''))
                            if 500 < val < 1500:
                                rate = val / 100.0
                                if validate_rate(rate, bank_code):
                                    return {
                                        "bank_code": bank_code,
                                        "bank_name": BANKS[bank_code]["name"],
                                        "short_name": BANKS[bank_code]["short_name"],
                                        "rate": round(rate, 4),
                                        "rate_type": "现汇卖出价",
                                        "publish_time": "",
                                        "source_url": url,
                                        "color": BANKS[bank_code]["color"],
                                        "status": "success"
                                    }
                        except ValueError:
                            continue

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return None


def fetch_cmb() -> Optional[Dict]:
    """招商银行 - 从官网解析"""
    bank_code = "CMB"
    print(f"Fetching {bank_code}...")
    try:
        url = "https://www.cmbchina.com/CmbWebPubInfo/RateResult.aspx?chnl=whjjckll"
        html = fetch_html_with_retry(url)
        soup = BeautifulSoup(html, 'html.parser')

        # 查找包含英镑的行
        rows = soup.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            cell_texts = [cell.get_text(strip=True) for cell in cells]
            row_text = ' '.join(cell_texts)

            if '英镑' in row_text or 'GBP' in row_text:
                for text in cell_texts:
                    try:
                        val = float(text.replace(',', ''))
                        if 500 < val < 1500:
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                return {
                                    "bank_code": bank_code,
                                    "bank_name": BANKS[bank_code]["name"],
                                    "short_name": BANKS[bank_code]["short_name"],
                                    "rate": round(rate, 4),
                                    "rate_type": "现汇卖出价",
                                    "publish_time": "",
                                    "source_url": url,
                                    "color": BANKS[bank_code]["color"],
                                    "status": "success"
                                }
                    except ValueError:
                        continue

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return None


def fetch_bocom() -> Optional[Dict]:
    """交通银行 - 从官网解析"""
    bank_code = "BOCOM"
    print(f"Fetching {bank_code}...")
    try:
        url = "https://www.bankcomm.com/BankCommSite/zonghang/cn/whpj/rmbwhpj/index.html"
        html = fetch_html_with_retry(url)
        soup = BeautifulSoup(html, 'html.parser')

        rows = soup.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 5:
                continue

            cell_texts = [cell.get_text(strip=True) for cell in cells]
            row_text = ' '.join(cell_texts)

            if '英镑' in row_text or 'GBP' in row_text:
                for text in cell_texts:
                    try:
                        val = float(text.replace(',', ''))
                        if 500 < val < 1500:
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                return {
                                    "bank_code": bank_code,
                                    "bank_name": BANKS[bank_code]["name"],
                                    "short_name": BANKS[bank_code]["short_name"],
                                    "rate": round(rate, 4),
                                    "rate_type": "现汇卖出价",
                                    "publish_time": "",
                                    "source_url": url,
                                    "color": BANKS[bank_code]["color"],
                                    "status": "success"
                                }
                    except ValueError:
                        continue

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
        return None


def fetch_abc() -> Optional[Dict]:
    """农业银行 - 从官网解析"""
    bank_code = "ABC"
    print(f"Fetching {bank_code}...")
    try:
        url = "https://www.abchina.com/cn/ForeignExchange/"
        html = fetch_html_with_retry(url)
        soup = BeautifulSoup(html, 'html.parser')

        rows = soup.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 5:
                continue

            cell_texts = [cell.get_text(strip=True) for cell in cells]
            row_text = ' '.join(cell_texts)

            if '英镑' in row_text or 'GBP' in row_text:
                for text in cell_texts:
                    try:
                        val = float(text.replace(',', ''))
                        if 500 < val < 1500:
                            rate = val / 100.0
                            if validate_rate(rate, bank_code):
                                return {
                                    "bank_code": bank_code,
                                    "bank_name": BANKS[bank_code]["name"],
                                    "short_name": BANKS[bank_code]["short_name"],
                                    "rate": round(rate, 4),
                                    "rate_type": "现汇卖出价",
                                    "publish_time": "",
                                    "source_url": url,
                                    "color": BANKS[bank_code]["color"],
                                    "status": "success"
                                }
                    except ValueError:
                        continue

        raise RuntimeError("Could not find GBP rate")
    except Exception as e:
        print(f"  Error fetching {bank_code}: {e}")
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

    # 使用线程池并行获取
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

    # 购汇时，卖出价越低越好
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
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ Successfully saved data to {filepath}")
    except Exception as e:
        print(f"ERROR: Failed to save data: {e}")
        raise


def main():
    output_path = Path("docs/data.json")

    print(f"Starting multi-bank GBP rate fetch at {datetime.now().isoformat()}")
    print("=" * 60)

    try:
        # 加载之前的数据
        previous_data = load_previous_data(output_path)

        # 获取所有银行汇率
        print("\nFetching rates from all banks...")
        banks = fetch_all_banks()

        if not banks:
            raise RuntimeError("Failed to fetch any bank rates")

        # 计算汇率变化
        banks = calculate_changes(banks, previous_data)

        # 按汇率排序（从低到高，低的更优）
        banks.sort(key=lambda x: x['rate'])

        # 找出最优汇率
        best = find_best_rate(banks)

        # 构建输出数据
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

        # 保存数据
        save_data(data, output_path)

        # 打印摘要
        print("\n" + "=" * 60)
        print("Summary:")
        print(f"  Total banks fetched: {len(banks)}")
        if best:
            print(f"  Best rate: {best['short_name']} - {best['rate']} CNY/GBP")
        print(f"  All rates:")
        for b in banks:
            change_str = ""
            if 'rate_change' in b:
                arrow = "↑" if b['rate_change'] > 0 else "↓" if b['rate_change'] < 0 else "→"
                change_str = f" ({arrow}{abs(b['rate_change']):.4f})"
            print(f"    {b['short_name']}: {b['rate']}{change_str}")

        print("\n✓ Task completed successfully")
        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Fatal error: {e}", file=sys.stderr)

        # 如果有旧数据，保持不变；否则写入错误状态
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
            except Exception as save_error:
                print(f"Could not save error state: {save_error}")

        sys.exit(1)


if __name__ == "__main__":
    main()
