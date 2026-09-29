import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]

NOTION_VERSION = "2025-09-03"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


# --------------------------------------------------
# 2. 네이버 ETF 시세 가져오기
# --------------------------------------------------

NAVER_URL = "https://finance.naver.com/api/sise/etfItemList.nhn"

response = requests.get(
    NAVER_URL,
    headers={
        "User-Agent": "Mozilla/5.0"
    },
    timeout=20
)

response.raise_for_status()

naver_data = response.json()

etf_list = naver_data["result"]["etfItemList"]

prices = {}

for item in etf_list:
    code = str(item.get("itemcode", "")).strip()
    price = item.get("nowVal")

    if code and price is not None:
        try:
            price = int(str(price).replace(",", ""))
            prices[code] = price
        except ValueError:
            pass

print(f"네이버에서 ETF {len(prices)}개를 가져왔습니다.")


# --------------------------------------------------
# 3. Notion 데이터 소스 ID 확인
# --------------------------------------------------

database_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"

db_response = requests.get(
    database_url,
    headers=NOTION_HEADERS,
    timeout=20
)

db_response.raise_for_status()

database = db_response.json()

data_sources = database.get("data_sources", [])

if not data_sources:
    raise Exception("Notion 데이터 소스를 찾을 수 없습니다.")

DATA_SOURCE_ID = data_sources[0]["id"]

print(f"Notion Data Source ID: {DATA_SOURCE_ID}")


# --------------------------------------------------
# 4. 보유종목 데이터 조회
# --------------------------------------------------

query_url = f"https://api.notion.com/v1/data_sources/{DATA_SOURCE_ID}/query"

pages = []
cursor = None

while True:

    payload = {}

    if cursor:
        payload["start_cursor"] = cursor

    query_response = requests.post(
        query_url,
        headers=NOTION_HEADERS,
        json=payload,
        timeout=20
    )

    query_response.raise_for_status()

    result = query_response.json()

    pages.extend(result.get("results", []))

    if not result.get("has_more"):
        break

    cursor = result.get("next_cursor")

print(f"Notion 보유종목 {len(pages)}개를 확인했습니다.")


# --------------------------------------------------
# 5. 종목코드 확인 → 현재가 업데이트
# --------------------------------------------------

updated_count = 0
skipped_count = 0

for page in pages:

    properties = page.get("properties", {})

    # 종목코드 속성
    code_property = properties.get("종목코드")

    if not code_property:
        print("종목코드 속성이 없어 건너뜁니다.")
        skipped_count += 1
        continue

    code = ""

    # Text
    if code_property.get("type") == "rich_text":
        rich_text = code_property.get("rich_text", [])

        if rich_text:
            code = rich_text[0].get("plain_text", "").strip()

    # 혹시 Title인 경우도 대응
    elif code_property.get("type") == "title":
        title = code_property.get("title", [])

        if title:
            code = title[0].get("plain_text", "").strip()

    if not code:
        print("종목코드가 비어 있어 건너뜁니다.")
        skipped_count += 1
        continue

    # 네이버 시세에 해당 종목이 없는 경우
    if code not in prices:
        print(f"{code}: 네이버 ETF 목록에서 찾지 못했습니다.")
        skipped_count += 1
        continue

    new_price = prices[code]

    # 현재 Notion에 저장된 가격 확인
    current_price = None

    price_property = properties.get("현재가")

    if price_property and price_property.get("type") == "number":
        current_price = price_property.get("number")

    # 가격이 동일하면 업데이트하지 않음
    if current_price == new_price:
        print(f"{code}: 현재가 {new_price:,}원 - 변경 없음")
        continue

    # --------------------------------------------------
    # Notion 페이지 업데이트
    # --------------------------------------------------

    page_id = page["id"]

    update_url = f"https://api.notion.com/v1/pages/{page_id}"

    update_payload = {
        "properties": {
            "현재가": {
                "number": new_price
            }
        }
    }

    update_response = requests.patch(
        update_url,
        headers=NOTION_HEADERS,
        json=update_payload,
        timeout=20
    )

    update_response.raise_for_status()

    print(
        f"{code}: "
        f"{current_price if current_price is not None else '-'} "
        f"→ {new_price:,}원"
    )

    updated_count += 1


print("--------------------------------")
print(f"업데이트 완료: {updated_count}개")
print(f"건너뜀: {skipped_count}개")
print("--------------------------------")
