# Hangcha StockCount v0.5.3 — 员工盘库合并

手机端 v0.4.5 与 v0.5.2 的手机文件完全一致。此版本只改变 PC 工作流：**先合并员工盘点结果，再在未来独立阶段更新正式库存 Excel**。不对照旧库存、不要求 Excel 行号、不生成归零或入库列、不修改原库存。

## 操作

1. Windows 安装 Python 3.10+（含 Tkinter），解压后双击 `desktop/启动管理员工具.bat`。合并员工 JSON 不需要 Microsoft Excel、pywin32 或网络。
2. 「导入员工 JSON」可多选，可补交文件。只接受手机 `hangcha-stockcount-export` v2。同 ID 取最新，最新删除状态不计入；同 ID 同时间内容不同、多个批次/基准混合会阻止导入。请使用每位员工最终完整导出。导出文件被复制进项目，不依赖原路径。
3. 「重复盘点冲突」以两条记录对照显示。同物理楼层、同零件（ERP 或 Part No. 至少一个匹配）、同库位或上下级库位重叠才标为疑似重复。不同备注号 1 和 10、不同箱层、不同楼层不因字符串前缀误报。不同零件可同库位存放；同一货架多人工作或重复完成标记仅在「库位覆盖提示」列出，不阻断合并。
4. 双击冲突或点击「处理选中冲突」：保留 A 排除 B、保留 B 排除 A，或确认两条都代表不同实物。人工处理需填写依据。每对重叠记录单独确认；新增或更改记录会重新检查，不会因旧确认而自动通过。要输入复盘数量或修改库位，可在「全部盘点记录」选择记录修改，然后排除重复记录；也可撤销排除。排除会影响该记录涉及的所有冲突。
5. 「合并库存预览」在无未解决冲突时显示每个 ERP + Part No. 组合、总数量和实际库位。支持小数和显式零库存。不同库位的相同编号组合自动累加，不要求原表存在该零件。不同编号组合保留为独立条目；缺少一个编号的记录也不猜测合并。原库存行匹配、编号映射及缺失物料处理留待下一阶段。
6. 「保存项目」保存全部导入文档、人工修正、重叠确认，之后「打开项目」恢复；旧 v0.5.2 项目不兼容，请重新导入员工原始导出。退出/打开其他项目时未保存修改有提示。
7. 确认已收集所有员工最终记录后，点击「生成合并库存 JSON」，选择新的文件名。无有效记录或仍有未解决冲突时禁止生成；不会覆盖已有文件。
8. 「生成手机基准（可选）」保留 v0.5.2 的旧表头识别工具，仅用于发放手机参考数据，与合并项目独立。此功能才需要 Windows 桌面 Excel 和 `py -3 -m pip install pywin32`。真实工作簿仍需验证。

## 合并库存 JSON 数据契约

`format: hangcha-stockcount-merged-inventory`, `version: 1`。UTF-8 JSON；所有数量为 JSON number（不取整，允许非负小数）。

- `session`, `snapshotId`: 批次及手机库存参考基准 ID。
- `scope: counted-items-only`, `unrecordedPolicy: unknown-not-zero`: 只包含有效盘点记录，未出现零件不代表库存 0；显式 0 则保存为 0。全表归零仅在未来 Excel 更新阶段经人工确认执行。
- `items[]`: 每个标准化（去首尾空格、大写、不移除标点）ERP + Part No. 组合一个汇总项。`erp`, `partNo`, `qty`, `rackNo`（正数量库位以 `/` 连接）、`locations[]`（楼层、库位、数量、员工及记录 ID，保留零数量库位）、`recordIds`, `workers`, `names`, `measurements`, `notes`。名称、尺寸、重量的不同观测值各自保留，缺失值不覆盖、不平均。后续 Excel 映射：`erp` → 商品明细码ERP，`partNo` → Part.No.，`qty` → 盘库入库，`rackNo` → Rack No.（更新规则待确认）。
- `acceptedRecords[]`: 全部有效修正后明细；`latestSourceRecords[]`: 每个 ID 最新原始记录（包括删除墓碑、人工排除、手机修订历史）。`recordDecisions[]`, `overlapDecisions[]`: 当前生效的人工决定和依据；`shelfCompletions[]`, `coverageAdvisories[]`: 完成标记及覆盖提示；`sourceExports[]`: 输入文件名、规范化 JSON 内容 SHA256、导出时间。完整历史输入保存在项目文件中。
- `identityPolicy: normalized-exact-erp-partNo-pair`: 不利用旧表自动推断编号对应关系。

例如同一零件在 A010203 盘点 12，在 B010203 盘点 0.5，结果 qty=12.5、rackNo=A010203/B010203，两处库位和原始记录均保留。复核前的疑似重复不会进入正式结果。

## 测试与边界

`cd desktop` 后运行 `py -3 -m unittest -v`。本版增加独立合并测试。旧 Excel 更新函数保留在 `stockcount.py` 中，但正常入口不提供生成 Excel 的操作，后续再对接合并 JSON。手机端仍使用原 GitHub Pages 根目录及同一域名。真实 Windows 界面与实际员工文件需现场验收。所有真实盘库文件、项目及导出 JSON 不得上传公开 GitHub 仓库。
