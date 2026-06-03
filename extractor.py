from llm_client import LLMClient


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
