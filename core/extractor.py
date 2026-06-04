from .llm_client import LLMClient
import json


class CompanyExtractor:
    def __init__(self, llm: LLMClient = None):
        self.llm = llm or LLMClient()

    def extract(self, text: str, query: str) -> list[str]:
        prompt = f"""Từ nội dung sau, hãy tìm tất cả các hãng/công ty sản xuất có liên quan đến lĩnh vực "{query}".
Chỉ trả về danh sách tên hãng (mỗi hãng 1 dòng), ko thêm giải thích.

Nội dung:
{text}"""
        content = self.llm.call("Bạn là chuyên gia trích xuất dữ liệu.", prompt)
        if not content:
            return []
        companies = []
        for line in content.split("\n"):
            line = line.strip().lstrip("- ").strip().lstrip("1234567890. ").strip()
            if line and len(line) > 2 and "công ty" not in line.lower() and "hãng" not in line.lower() and "dưới" not in line.lower():
                companies.append(line)
        return companies


    def matchCompany(self, homepage_content: str, query: str):
        prompt = f"""Bạn là chuyên gia phân tích công ty.

Dưới đây là nội dung trang chủ:
<homepage>
{homepage_content}
</homepage>

Nhiệm vụ:
1. Xác định công ty có cung cấp sản phẩm/giải pháp có khả năng cao liên quan đến "{query}" không
2. Nếu có, liệt kê các sản phẩm/giải pháp liên quan được nhắc đến trong nội dung

Chỉ trả về JSON đúng format:
{{
"answer": true/false,
"products": ["product1", "product2"]
}}

Nếu không có thì products = []"""

        response = self.llm.call("Bạn là chuyên gia phân tích.", prompt)

        try:
            data = json.loads(response)
            return data
        except:
            return {"answer": False, "products": []}
