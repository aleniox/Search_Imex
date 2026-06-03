class ReportCompiler:
    def compile(self, user_query: str, companies: list[str], homepages: list[dict]) -> str:
        lines = ["BÁO CÁO HÃNG SẢN XUẤT ĐÁP ỨNG YÊU CẦU", "=" * 50, ""]
        lines.append(f"Yêu cầu: {user_query}")
        lines.append(f"Số hãng tìm thấy: {len(companies)}")
        lines.append("")
        for i, company in enumerate(companies, 1):
            lines.append(f"{i}. {company}")
            hp = next((h["url"] for h in homepages if h["company"] == company), "")
            if hp:
                lines.append(f"   🔗 {hp}")
            lines.append("")
        return "\n".join(lines)
