#!/usr/bin/env python3
"""
多银行英镑汇率抓取脚本
支持银行：中国银行、工商银行、建设银行、招商银行、交通银行、农业银行
使用 Playwright 渲染 JavaScript 页面
"""

import json
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List

# 尝试导入 Playwright (用于 JS 渲染)
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("Warning: Playwright not available, some banks may not work")

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: BeautifulSoup not installed. Run: pip install beautifulsoup4")
    sys.exit(1)

# 英镑汇率合理范围（仅用于最终验证，不用于筛选）
VALID_RATE_RANGE = (5.0, 15.0)

# 银行配置
BANKS = {
    "BOC": {
        "name": "中国银行",
        "short_name": "中行",
        "url": "https://www.boc.cn/sourcedb/whpj/",
        "color": "#e60012",
        "needs_js": False
    },
    "ICBC": {
        "name": "中国工商银行",
        "short_name": "工行",
        "url": "https://www.icbc.com.cn/column/1438058341489590354.html",
        "color": "#c4161c",
        "needs_js": True
    },
    "CCB": {
        "name": "中国建设银行",
        "short_name": "建行",
        "url": "https://www2.ccb.com/chn/forex/exchange-quotations.shtml",
        "color": "#004098",
        "needs_js": True
    },
    "CMB": {
        "name": "招商银行",
        "short_name": "招行",
        "url": "https://fx.cmbchina.com/hq/",
        "color": "#c41230",
        "needs_js": True
    },
    "BOCOM": {
        "name": "交通银行",
        "short_name": "交行",
        "url": "https://www.bankcomm.com/BankCommSite/shtml/jyjr/cn/7158/7161/8091/list.shtml",
        "color": "#004a8f",
        "needs_js": True
    },
    "ABC": {
        "name": "中国农业银行",
        "short_name": "农行",
        "url": "https://ewealth.abchina.com/foreignexchange/listprice/",
        "color": "#007f4e",
        "needs_js": True
    },
    "HSBC": {
        "name": "汇丰银行",
        "short_name": "汇丰",
        "url": "https://www.services.cn-banking.hsbc.com.cn/PublicContent/common/rate/zh/exchange-rates.html",
        "color": "#db0011",
        "needs_js": False
    }
}


def validate_rate(rate: float, bank_code: str) -> bool:
    """验证汇率是否在合理范围内"""
    if not (VALID_RATE_RANGE[0] <= rate <= VALID_RATE_RANGE[1]):
        print(f"    Warning: {bank_code} rate {rate} outside valid range")
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


def is_gbp_currency_cell(text: str) -> bool:
    """检查单元格是否是英镑币种标识"""
    text = text.strip().upper()
    # 必须包含英镑或GBP，但不能是纯数字
    if '英镑' in text or 'GBP' in text:
        # 确保这是币种名称，不是其他内容
        return True
    return False


def extract_gbp_rate_from_html(html: str, bank_code: str) -> Optional[tuple]:
    """从HTML中提取英镑汇率 - 简化版：找到英镑行，取较高值作为卖出价"""
    soup = BeautifulSoup(html, 'html.parser')

    # 方法1：查找表格行
    for row in soup.find_all('tr'):
        cells = row.find_all(['td', 'th'])  # 也检查 th 元素
        if not cells:
            continue

        cell_texts = [c.get_text(strip=True).replace(',', '').replace('\xa0', ' ') for c in cells]
        row_text = ' '.join(cell_texts)

        # 检查是否包含英镑
        if '英镑' not in row_text and 'GBP' not in row_text:
            continue

        print(f"    Found GBP row: {cell_texts[:6]}")

        # 提取所有数值
        rates_found = []
        for text in cell_texts:
            try:
                val = float(text)
                # 100外币 = xxx人民币 格式
                if 100 < val < 2000:
                    rates_found.append(val / 100.0)
                # 直接汇率格式 (英镑通常在 8-12 之间，但要留余地)
                elif 5 < val < 20:
                    rates_found.append(val)
            except ValueError:
                continue

        if rates_found:
            print(f"    Rates found: {rates_found}")
            # 取最高值作为卖出价（卖出价总是 >= 买入价）
            rate = max(rates_found)
            print(f"    Selected (max): {rate}")

            if validate_rate(rate, bank_code):
                # 尝试提取发布时间
                publish_time = ""
                for text in cell_texts:
                    if re.match(r'\d{4}[-/]\d{2}[-/]\d{2}', text):
                        publish_time = text
                        break
                return rate, publish_time

    # 方法2：如果表格方法失败，尝试用正则搜索整个页面
    # 注意：HSBC等网站HTML标签很多，需要灵活匹配
    patterns = [
        r'GBP\).*?(\d\.\d{4,})',            # HSBC格式: GBP)...9.6157267
        r'英镑.*?(\d\.\d{4,})',             # 通用：英镑...9.xxxx
        r'GBP\)</td><td[^>]*>(\d+\.\d+)',   # HSBC表格格式
        r'英镑.*?</td>.*?<td[^>]*>(\d+\.\d+)',  # 通用表格格式
        r'英镑[^0-9]{0,200}(\d+\.\d{2,})',  # 英镑后面的小数
        r'GBP[^0-9]{0,200}(\d+\.\d{2,})',   # GBP后面的小数
        r'(\d{3}\.\d+)[^0-9]{0,50}英镑',    # 英镑前面的数字
    ]

    # 调试：对于HSBC，打印GBP附近的内容
    if bank_code == "HSBC":
        gbp_pos = html.find("GBP")
        if gbp_pos >= 0:
            snippet = html[gbp_pos:gbp_pos+200].replace('\n', ' ')
            print(f"    [DEBUG] GBP context: {snippet[:150]}")

    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        if matches:
            rates = []
            for m in matches:
                try:
                    val = float(m)
                    if 800 < val < 1300:  # 100外币格式，英镑约 900-1000
                        rates.append(val / 100.0)
                    elif 8 < val < 13:  # 直接格式，英镑约 9-10
                        rates.append(val)
                except ValueError:
                    pass
            if rates:
                rate = max(rates)
                print(f"    Found via regex ({pattern[:20]}...): {rate}")
                if validate_rate(rate, bank_code):
                    return rate, ""

    return None


def fetch_with_playwright(url: str, bank_code: str, timeout: int = 30000) -> Optional[str]:
    """使用 Playwright 获取 JavaScript 渲染后的页面"""
    if not HAS_PLAYWRIGHT:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()

            print(f"    Loading with Playwright...")
            page.goto(url, timeout=timeout, wait_until="networkidle")

            # 等待表格加载
            try:
                page.wait_for_selector("table", timeout=10000)
            except:
                pass

            # 额外等待一下确保数据加载
            page.wait_for_timeout(2000)

            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"    Playwright error: {e}")
        return None


def fetch_with_urllib(url: str) -> Optional[str]:
    """使用 urllib 获取页面（用于静态页面）"""
    import ssl
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError

    # 创建允许旧 SSL 的上下文
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    if hasattr(ssl, 'OP_LEGACY_SERVER_CONNECT'):
        ssl_context.options |= ssl.OP_LEGACY_SERVER_CONNECT
    else:
        ssl_context.options |= 0x4

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=30, context=ssl_context) as resp:
            content = resp.read()
            # 尝试多种编码
            for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
                try:
                    return content.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return content.decode('utf-8', errors='ignore')
    except (URLError, HTTPError) as e:
        print(f"    urllib error: {e}")
        return None


def fetch_bank(bank_code: str) -> Optional[Dict]:
    """获取单个银行的汇率"""
    config = BANKS[bank_code]
    url = config["url"]
    needs_js = config["needs_js"]

    print(f"Fetching {bank_code} ({config['short_name']})...")
    print(f"  URL: {url}")

    html = None

    # 如果需要 JavaScript 渲染
    if needs_js and HAS_PLAYWRIGHT:
        html = fetch_with_playwright(url, bank_code)

    # 如果 Playwright 失败或不需要 JS，尝试普通请求
    if not html:
        html = fetch_with_urllib(url)

    if not html:
        print(f"  ✗ {bank_code}: Failed to fetch page")
        return None

    # 检查是否有 GBP 数据
    has_gbp = '英镑' in html or 'GBP' in html
    print(f"    Page length: {len(html)}, has GBP: {has_gbp}")

    if not has_gbp:
        print(f"  ✗ {bank_code}: GBP not found in page")
        return None

    # 提取汇率
    result = extract_gbp_rate_from_html(html, bank_code)
    if result:
        rate, publish_time = result
        print(f"  ✓ {bank_code}: {rate}")
        return make_result(bank_code, rate, publish_time)

    print(f"  ✗ {bank_code}: Could not extract rate")
    return None


def fetch_all_banks() -> List[Dict]:
    """获取所有银行汇率"""
    results = []

    for bank_code in BANKS:
        try:
            result = fetch_bank(bank_code)
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
    print(f"Playwright available: {HAS_PLAYWRIGHT}")

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
