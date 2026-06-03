import asyncio
import logging
import re
from dotenv import load_dotenv

import gradio as gr

from agents.product_discovery import ProductDiscoveryAgent
from agents.priority_exhibition import PriorityExhibitionAgent

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

LOG_CAPTURE = []


class ListHandler(logging.Handler):
    def emit(self, record):
        LOG_CAPTURE.append(self.format(record))


handler = ListHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(handler)


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def make_progress_callback(progress: gr.Progress):
    def cb(pct: float, desc: str = ""):
        progress(pct, desc=desc)
    return cb


async def run_agent(agent_type, provider, query, excel_path, progress=gr.Progress()):
    progress(0, desc="Khởi động...")
    await asyncio.sleep(0.01)
    LOG_CAPTURE.clear()
    cb = make_progress_callback(progress)
    try:
        if agent_type == "ProductDiscoveryAgent":
            progress(0.01, desc="Khởi tạo ProductDiscoveryAgent...")
            await asyncio.sleep(0.01)
            agent = ProductDiscoveryAgent(search_provider=provider, progress_callback=cb)
            result = await agent.run(query)
        else:
            if not excel_path.strip():
                return "Vui lòng nhập đường dẫn file Excel", "Thiếu Excel path"
            import os
            if not os.path.exists(excel_path.strip()):
                return f"File không tồn tại: {excel_path.strip()}", "Lỗi đường dẫn"
            progress(0.01, desc="Khởi tạo PriorityExhibitionAgent...")
            await asyncio.sleep(0.01)
            agent = PriorityExhibitionAgent(search_provider=provider, progress_callback=cb)
            result = await agent.run(excel_path.strip(), query)
        log_text = "\n".join(strip_ansi(l) for l in LOG_CAPTURE[-100:])
        return result, log_text
    except Exception as e:
        LOG_CAPTURE.append(f"LỖI: {e}")
        log_text = "\n".join(strip_ansi(l) for l in LOG_CAPTURE[-100:])
        return f"Lỗi: {e}", log_text


def toggle_excel(agent_type):
    return gr.update(visible=agent_type == "PriorityExhibitionAgent")


with gr.Blocks(title="Search Agent UI") as demo:
    gr.Markdown("# 🔍 Search Agent UI")

    with gr.Row():
        with gr.Column(scale=1):
            agent_type = gr.Dropdown(
                choices=["ProductDiscoveryAgent", "PriorityExhibitionAgent"],
                value="ProductDiscoveryAgent",
                label="Agent",
            )
        with gr.Column(scale=1):
            provider = gr.Dropdown(
                choices=["duckduckgo", "tavily", "serpapi"],
                value="duckduckgo",
                label="Search Provider",
            )

    query = gr.Textbox(label="Yêu cầu (query)", placeholder="VD: Phần mềm phân tích mã độc cho hệ thống máy tính")
    excel_path = gr.Textbox(
        label="Đường dẫn file Excel",
        placeholder=r"C:\Users\PC\Downloads\searchs\data\AIPT_Global_Defense_Security_Exhibitions_Full_Database.xlsx",
        visible=False,
    )

    agent_type.change(fn=toggle_excel, inputs=agent_type, outputs=excel_path)

    run_btn = gr.Button("▶ Run", variant="primary", size="lg")

    result_box = gr.Textbox(label="Kết quả", lines=20, max_lines=40)
    log_box = gr.Textbox(label="Log", lines=10, max_lines=20)

    run_btn.click(
        fn=run_agent,
        inputs=[agent_type, provider, query, excel_path],
        outputs=[result_box, log_box],
    )


if __name__ == "__main__":
    demo.queue()
    demo.launch(theme=gr.themes.Soft())
