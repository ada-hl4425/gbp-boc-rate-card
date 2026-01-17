#!/usr/bin/env python3
"""
改进版中国银行英镑汇率抓取脚本
- 使用 BeautifulSoup 进行 HTML 解析
- 添加完整错误处理和重试机制
- 数据验证和合理性检查
- 更好的日志记录
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: BeautifulSoup not installed. Run: pip install beautifulsoup4")
    sys.exit(1)


BOC_URL = "https://www.boc.cn/sourcedb/whpj/"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
VALID_RATE_RANGE = (5.0, 15.0)  # 合理汇率范围 CNY per GBP


def fetch_html_with_retry(url: str, retries: int = MAX_RETRIES) -> str:
    """带重试机制的 HTML 获取"""
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except (URLError, HTTPError) as e:
            print(f"Attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(f"Failed to fetch after {retries} attempts") from e
    return ""


def parse_gbp_rate_bs4(html: str) -> Dict:
    """使用 BeautifulSoup 解析中行英镑汇率"""
    soup = BeautifulSoup(html, 'html.parser')
    
    # 查找所有表格行
    rows = soup.find_all('tr')
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 7:
            continue
        
        # 提取文本并清理空白
        cell_texts = [cell.get_text(strip=True) for cell in cells]
        
        # 检查是否为英镑行（货币名称包含"英镑"或"GBP"）
        currency_name = cell_texts[0]
        if '英镑' not in currency_name and 'GBP' not in currency_name:
            continue
        
        try:
            # 中行格式：货币名称 | 现汇买入价 | 现钞买入价 | 现汇卖出价 | 现钞卖出价 | 中行折算价 | 发布时间
            cash_selling_str = cell_texts[3].replace(',', '')  # 现汇卖出价
            publish_time = cell_texts[6]
            
            # 中行报价是"100外币 = X人民币"
            rate_per_100 = float(cash_selling_str)
            rate_per_1 = rate_per_100 / 100.0
            
            # 数据验证
            if not (VALID_RATE_RANGE[0] <= rate_per_1 <= VALID_RATE_RANGE[1]):
                raise ValueError(
                    f"Rate {rate_per_1} is outside valid range {VALID_RATE_RANGE}"
                )
            
            return {
                "currency": currency_name,
                "pair": "GBP/CNY",
                "boc_field": "现汇卖出价",
                "rate_cny_per_gbp": round(rate_per_1, 4),
                "rate_cny_per_100_gbp": round(rate_per_100, 2),
                "publish_time_raw": publish_time,
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "fetched_at_beijing": datetime.now(timezone.utc).astimezone(
                    tz=None
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "source": BOC_URL,
                "status": "success"
            }
        
        except (ValueError, IndexError) as e:
            print(f"Error parsing GBP row: {e}")
            print(f"Row data: {cell_texts}")
            continue
    
    raise RuntimeError("Could not find or parse GBP rate from BOC page")


def load_previous_data(filepath: Path) -> Optional[Dict]:
    """加载上一次的数据作为备份"""
    try:
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load previous data: {e}")
    return None


def save_data(data: Dict, filepath: Path, previous_data: Optional[Dict] = None):
    """保存数据，如果失败则保留旧数据"""
    try:
        # 添加变化信息
        if previous_data and 'rate_cny_per_gbp' in previous_data:
            old_rate = previous_data['rate_cny_per_gbp']
            new_rate = data['rate_cny_per_gbp']
            change = new_rate - old_rate
            data['rate_change'] = round(change, 4)
            data['rate_change_percent'] = round((change / old_rate) * 100, 2)
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✓ Successfully saved data to {filepath}")
        print(f"  Rate: 1 GBP = {data['rate_cny_per_gbp']} CNY")
        if 'rate_change' in data:
            print(f"  Change: {data['rate_change']:+.4f} ({data['rate_change_percent']:+.2f}%)")
    
    except Exception as e:
        print(f"ERROR: Failed to save data: {e}")
        if previous_data:
            print("Keeping previous data unchanged")
        raise


def main():
    output_path = Path("docs/data.json")
    
    print(f"Starting BOC GBP rate fetch at {datetime.now().isoformat()}")
    
    try:
        # 加载之前的数据
        previous_data = load_previous_data(output_path)
        
        # 抓取新数据
        html = fetch_html_with_retry(BOC_URL)
        data = parse_gbp_rate_bs4(html)
        
        # 保存数据
        save_data(data, output_path, previous_data)
        
        print("✓ Task completed successfully")
        sys.exit(0)
    
    except Exception as e:
        print(f"✗ Fatal error: {e}", file=sys.stderr)
        
        # 如果有旧数据，保持不变；否则写入错误状态
        if not output_path.exists():
            error_data = {
                "status": "error",
                "error_message": str(e),
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": BOC_URL
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
