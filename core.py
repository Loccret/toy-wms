import gradio as gr
import pandas as pd
import os
from datetime import datetime
from PIL import Image
import shutil  # For copying files

# -------------------------------
# Setup: Data Directory, Log Folder & CSV Files
# -------------------------------
DATA_DIR = "./data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Create log folder if it does not exist.
LOG_DIR = os.path.join(DATA_DIR, "log")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

TRANSACTION_CSV = os.path.join(DATA_DIR, "transaction_records.csv")
INVENTORY_CSV = os.path.join(DATA_DIR, "warehouse_inventory.csv")

# Initialize or load the Transaction Records DataFrame
if os.path.exists(TRANSACTION_CSV):
    df_transactions = pd.read_csv(TRANSACTION_CSV, parse_dates=["日期"])
else:
    df_transactions = pd.DataFrame(columns=["日期", "出入库", "物品", "发送方(接收方)", "经办人", "备注"])
    df_transactions.to_csv(TRANSACTION_CSV, index=False)

# Initialize or load the Warehouse Inventory DataFrame
if os.path.exists(INVENTORY_CSV):
    df_inventory = pd.read_csv(INVENTORY_CSV, parse_dates=["最后改变时间"])
else:
    df_inventory = pd.DataFrame(columns=["最后改变时间", "物品", "在库数量"])
    df_inventory.to_csv(INVENTORY_CSV, index=False)

# -------------------------------
# Undo/Redo Stacks
# -------------------------------
undo_stack = []
redo_stack = []

# -------------------------------
# Logging Function
# -------------------------------
def log_files():
    """
    Copies the current transaction and inventory CSV files into the log folder,
    naming them with a timestamp prefix in the format YYYYMMDDHHMMSS.
    """
    log_folder = os.path.join(DATA_DIR, "log")
    if not os.path.exists(log_folder):
        os.makedirs(log_folder)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if os.path.exists(TRANSACTION_CSV):
        shutil.copy(TRANSACTION_CSV, os.path.join(log_folder, f"{timestamp}-transaction_records.csv"))
    if os.path.exists(INVENTORY_CSV):
        shutil.copy(INVENTORY_CSV, os.path.join(log_folder, f"{timestamp}-warehouse_inventory.csv"))

# -------------------------------
# Utility Functions for Saving
# -------------------------------
def save_transactions():
    df_transactions.to_csv(TRANSACTION_CSV, index=False)

def save_inventory():
    df_inventory.to_csv(INVENTORY_CSV, index=False)

# -------------------------------
# Inventory Update Logic
# -------------------------------
def update_inventory(item, transaction_type, quantity):
    """
    Updates the warehouse inventory when a new transaction is added.
    For inbound, increases stock; for outbound, decreases stock.
    Returns (True, message) on success or (False, error message) if outbound would make stock negative.
    """
    global df_inventory
    now = datetime.now()
    if item in df_inventory["物品"].values:
        idx = df_inventory.index[df_inventory["物品"] == item][0]
        current_stock = int(df_inventory.loc[idx, "在库数量"])
        if transaction_type == "入库":
            new_stock = current_stock + quantity
        else:  # "出库"
            new_stock = current_stock - quantity
            if new_stock < 0:
                return False, f"Error: 出库操作导致物品 '{item}' 库存为负！"
        df_inventory.loc[idx, "在库数量"] = new_stock
        df_inventory.loc[idx, "最后改变时间"] = now
    else:
        if transaction_type == "入库":
            new_row = {"最后改变时间": now, "物品": item, "在库数量": quantity}
            df_inventory = pd.concat([df_inventory, pd.DataFrame([new_row])], ignore_index=True)
        else:
            return False, f"Error: 物品 '{item}' 不存在于库存中，无法出库！"
    save_inventory()
    return True, "库存已更新。"

# -------------------------------
# Transaction Functions
# -------------------------------
def process_image(file_obj):
    """
    Saves the uploaded image file to the data folder and returns the saved file path.
    """
    if file_obj is None:
        return ""
    filename = os.path.basename(file_obj.name)
    dest_path = os.path.join(DATA_DIR, filename)
    with open(dest_path, "wb") as f:
        f.write(file_obj.read())
    return dest_path

def add_inbound(item, sender_receiver, operator, remarks, quantity, image):
    """
    Records an inbound (入库) transaction.
    Logs the current CSVs, saves the current state for undo, clears redo history,
    then updates the transaction records and inventory.
    """
    global df_transactions, undo_stack, redo_stack
    log_files()  # Log current CSV files
    undo_stack.append((df_transactions.copy(), df_inventory.copy()))
    redo_stack.clear()
    
    now = datetime.now()
    transaction_type = "入库"
    quantity = int(quantity)
    image_path = process_image(image)
    if image_path:
        remarks = f"{remarks} || image:{image_path}"
    record = {
        "日期": now,
        "出入库": transaction_type,
        "物品": item,
        "发送方(接收方)": sender_receiver,
        "经办人": operator,
        "备注": remarks,
    }
    success, msg = update_inventory(item, transaction_type, quantity)
    if not success:
        return msg
    # Simply concatenate the new record
    df_transactions = pd.concat([df_transactions, pd.DataFrame([record])], ignore_index=True)
    save_transactions()
    return "入库交易记录成功。"

def add_outbound(item, sender_receiver, operator, remarks, quantity, image):
    """
    Records an outbound (出库) transaction.
    Logs the current CSVs, saves the current state for undo, clears redo history,
    validates inventory and updates records.
    """
    global df_transactions, undo_stack, redo_stack
    log_files()  # Log current CSV files
    undo_stack.append((df_transactions.copy(), df_inventory.copy()))
    redo_stack.clear()
    
    now = datetime.now()
    transaction_type = "出库"
    quantity = int(quantity)
    image_path = process_image(image)
    if image_path:
        remarks = f"{remarks} || image:{image_path}"
    success, msg = update_inventory(item, transaction_type, quantity)
    if not success:
        return msg
    record = {
        "日期": now,
        "出入库": transaction_type,
        "物品": item,
        "发送方(接收方)": sender_receiver,
        "经办人": operator,
        "备注": remarks,
    }
    df_transactions = pd.concat([df_transactions, pd.DataFrame([record])], ignore_index=True)
    save_transactions()
    return "出库交易记录成功。"

# -------------------------------
# Undo/Redo Functions
# -------------------------------
def undo_action():
    """
    Reverts to the previous state from the undo stack.
    The current state is pushed to the redo stack.
    """
    global df_transactions, df_inventory, undo_stack, redo_stack
    if not undo_stack:
        return "无法撤销操作，没有历史记录。", df_transactions
    redo_stack.append((df_transactions.copy(), df_inventory.copy()))
    state = undo_stack.pop()
    df_transactions, df_inventory = state
    save_transactions()
    save_inventory()
    return "撤销成功。", df_transactions

def redo_action():
    """
    Reapplies a state from the redo stack.
    The current state is pushed to the undo stack.
    """
    global df_transactions, df_inventory, undo_stack, redo_stack
    if not redo_stack:
        return "无法重做操作，没有重做记录。", df_transactions
    undo_stack.append((df_transactions.copy(), df_inventory.copy()))
    state = redo_stack.pop()
    df_transactions, df_inventory = state
    save_transactions()
    save_inventory()
    return "重做成功。", df_transactions

# -------------------------------
# CSV File Import Functions
# -------------------------------
def load_transactions_file(file_obj):
    global df_transactions
    dest = TRANSACTION_CSV
    if file_obj is None:
        if os.path.exists(dest):
            df_transactions = pd.read_csv(dest, parse_dates=["日期"])
            return "出入库记录已加载。"
        else:
            return "未上传文件且交易记录文件不存在。"
    else:
        if hasattr(file_obj, "read"):
            data = file_obj.read()
        else:
            with open(file_obj, "rb") as f:
                data = f.read()
        with open(dest, "wb") as f:
            f.write(data)
        df_transactions = pd.read_csv(dest, parse_dates=["日期"])
        return "出入库记录已加载。"

def load_inventory_file(file_obj):
    global df_inventory
    dest = INVENTORY_CSV
    if file_obj is None:
        if os.path.exists(dest):
            df_inventory = pd.read_csv(dest, parse_dates=["最后改变时间"])
            return "仓库库存已加载。"
        else:
            return "未上传文件且仓库文件不存在。"
    else:
        if hasattr(file_obj, "read"):
            data = file_obj.read()
        else:
            with open(file_obj, "rb") as f:
                data = f.read()
        with open(dest, "wb") as f:
            f.write(data)
        df_inventory = pd.read_csv(dest, parse_dates=["最后改变时间"])
        return "仓库库存已加载。"

# -------------------------------
# Filtering & Refresh Functions
# -------------------------------
def filter_dataframe(df, keyword):
    if keyword.strip() == "":
        return df
    keyword_lower = keyword.lower()
    filtered = df[df.apply(lambda row: row.astype(str).str.lower().str.contains(keyword_lower).any(), axis=1)]
    return filtered

def update_transactions_display(keyword):
    return filter_dataframe(df_transactions, keyword)

def update_inventory_display(keyword):
    return filter_dataframe(df_inventory, keyword)

def refresh_transactions():
    return df_transactions

def refresh_inventory():
    return df_inventory

# -------------------------------
# Gradio UI Construction
# -------------------------------
with gr.Blocks() as demo:
    gr.Markdown("## Warehouse Management System (WMS)")
    
    with gr.Row():
        with gr.Column():
            gr.Markdown("### 新交易 (New Transaction)")
            with gr.Tabs():
                with gr.TabItem("入库 (Inbound)"):
                    item_in = gr.Textbox(label="物品")
                    sender_in = gr.Textbox(label="发送方(接收方)")
                    operator_in = gr.Textbox(label="经办人")
                    quantity_in = gr.Number(label="数量", value=1, precision=0)
                    remarks_in = gr.Textbox(label="备注")
                    image_in = gr.File(label="备注图片 (可选)", file_count="single", file_types=["image"])
                    btn_inbound = gr.Button("记录入库")
                    inbound_result = gr.Textbox(label="入库结果", interactive=False)
                with gr.TabItem("出库 (Outbound)"):
                    item_out = gr.Textbox(label="物品")
                    sender_out = gr.Textbox(label="发送方(接收方)")
                    operator_out = gr.Textbox(label="经办人")
                    quantity_out = gr.Number(label="数量", value=1, precision=0)
                    remarks_out = gr.Textbox(label="备注")
                    image_out = gr.File(label="备注图片 (可选)", file_count="single", file_types=["image"])
                    btn_outbound = gr.Button("记录出库")
                    outbound_result = gr.Textbox(label="出库结果", interactive=False)
        with gr.Column():
            gr.Markdown("### CSV 导入")
            trans_file = gr.File(label="拖拽上传 出入库记录 CSV", file_types=[".csv"])
            inv_file = gr.File(label="拖拽上传 仓库 CSV", file_types=[".csv"])
            btn_load_trans = gr.Button("读取出入库记录")
            btn_load_inv = gr.Button("读取仓库")
            load_trans_result = gr.Textbox(label="读取出入库记录结果", interactive=False)
            load_inv_result = gr.Textbox(label="读取仓库结果", interactive=False)
    
    with gr.Tabs():
        with gr.TabItem("出入库记录 (Transaction Records)"):
            with gr.Row():
                undo_btn = gr.Button("撤销")
                redo_btn = gr.Button("重做")
            undo_msg = gr.Textbox(label="操作信息", interactive=False)
            keyword_trans = gr.Textbox(label="关键词过滤")
            df_trans_display = gr.Dataframe(value=df_transactions, interactive=True, label="出入库记录")
            btn_refresh_trans = gr.Button("刷新记录表")
        with gr.TabItem("仓库 (Warehouse Inventory)"):
            keyword_inv = gr.Textbox(label="关键词过滤")
            df_inv_display = gr.Dataframe(value=df_inventory, interactive=True, label="仓库")
            btn_refresh_inv = gr.Button("刷新库存表")
    
    # -------------------------------
    # Button Actions / Callbacks
    # -------------------------------
    btn_inbound.click(fn=add_inbound,
                      inputs=[item_in, sender_in, operator_in, remarks_in, quantity_in, image_in],
                      outputs=inbound_result)
    
    btn_outbound.click(fn=add_outbound,
                       inputs=[item_out, sender_out, operator_out, remarks_out, quantity_out, image_out],
                       outputs=outbound_result)
    
    btn_load_trans.click(fn=load_transactions_file, inputs=trans_file, outputs=load_trans_result)
    btn_load_inv.click(fn=load_inventory_file, inputs=inv_file, outputs=load_inv_result)
    
    undo_btn.click(fn=undo_action, outputs=[undo_msg, df_trans_display])
    redo_btn.click(fn=redo_action, outputs=[undo_msg, df_trans_display])
    
    keyword_trans.change(fn=update_transactions_display, inputs=keyword_trans, outputs=df_trans_display)
    keyword_inv.change(fn=update_inventory_display, inputs=keyword_inv, outputs=df_inv_display)
    
    btn_refresh_trans.click(fn=refresh_transactions, outputs=df_trans_display)
    btn_refresh_inv.click(fn=refresh_inventory, outputs=df_inv_display)

demo.launch()
