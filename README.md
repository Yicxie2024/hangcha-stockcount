# Hangcha StockCount v0.4.3 · 离线盘库

> 手机盘点 + Windows 电脑汇总。**无需后端服务器**。网站只分发静态程序，不收集库存或盘点数据。

## 目录结构

```
index.html / app.js / styles.css / sw.js / manifest.webmanifest / icon.svg
    GitHub Pages 静态网页，直接放在仓库根目录

desktop/
    stockcount.py             Python 管理端（标准库，无额外安装依赖）
    mapping.json              Excel 表头配置
    启动管理员工具.bat           Windows 图形操作入口

examples/
    演示手机库存.json / 演示员工A_盘点记录.json（均为虚构演示数据）

tests/
    本地回归测试

.gitignore                  防止把真实库存、员工记录提交到公开仓库
.nojekyll                   让 GitHub Pages 原样提供静态文件
```

## GitHub Pages 部署

1. 先从已有手机 App 的「记录」页面导出盘点 JSON 备份。
2. 将这个 ZIP **解压后的内容**提交到现有 `hangcha-stockcount` 仓库根目录。`index.html` 必须直接在根目录，不要整体上传 ZIP，也不要外面多一层文件夹。
3. Settings → Pages：Deploy from a branch → `main` → `/(root)`；Actions 确认 Pages 构建成功。
4. 手机联网打开 `https://yicxie2024.github.io/hangcha-stockcount/`，确认版本为 `v0.4.3`，并重新测试飞行模式打开、保存、导出。

**重要：** GitHub 仓库是公开的。这个完整仓库包只含程序和虚构演示数据，**不包含《已有备件26年10月28日.xlsx》或真实手机库存 JSON**。请始终在手机上用“导入库存 JSON”加载真实清单。不要把真实员工盘点导出文件、库存基准或业务报告放进公开仓库。

## 手机端操作（本版变更）

- 正常录入：楼层→列→货架号→高度→箱号→箱层→库位备注号→零件→尺寸重量→数量→备注→保存。固定选项点选后自动前进。
- **临时修改固定选项**（楼层/列/货架号/高度/箱号/箱层，或选中的零件候选）：点击即应用到当前未保存草稿，并回到之前工作位置；楼层至箱层的界面**不再出现“确认手动输入”按钮**。
- **临时清空可选字段**：点一次“× 清空”，即清空当前节点并回到原工作位置；但如果清空某个上级库位会影响**已录入下级库位**，会明确征求一次连带清空同意。取消不会丢失旧值。
- **临时手动输入**：备注号、手动零件编号、尺寸/重量、数量和备注等需要键盘输入的字段，继续保留“确认手动输入”；正常录入中的操作逻辑不变。
- 删除了“清空全部尺寸”按钮；长/宽/高可以分别清空。
- **盘点记录列表左滑**：出现“编辑”“删除”两个选项；点“⋯”亦可展开（方便电脑测试和无障碍操作）。点击删除不弹确认框，但会显示“撤销删除”短暂操作条；删除后记录从列表消失。
- 手机**不会物理移除被删记录**，而是保存 `deleted:true` 的墓碑状态、更新时间、记录 ID。所有记录（包括墓碑）都包含在导出 JSON 中；这是避免旧版本导出重复进入合并结果的必要措施。
- 工作中断：仍保留本地草稿、部分输入、ERP/Part No. 搜索词、历史编辑原记录 ID，完整的最终保存行为不变。

## Windows 管理端

电脑安装 Python 3.10+ 后，双击 `desktop/启动管理员工具.bat`，按界面导入年度库存 Excel，生成手机库存 JSON；收集多位员工导出的 JSON 后，选择文件夹生成核对报告。

或者在命令行运行（在仓库根目录）：

```powershell
py desktop/stockcount.py inspect "D:\库存\已有备件.xlsx"
py desktop/stockcount.py prepare "D:\库存\已有备件.xlsx" --out "D:\库存\mobile-catalog.json"
py desktop/stockcount.py merge "D:\库存\已有备件.xlsx" "D:\盘库导出" --out "D:\盘库报告.xlsx"
```

电脑合并逻辑：同一个记录 ID 的多个导出版本按 `updatedAt` 选最新版本；最终是 `deleted:true` 则不计入有效库存。报告额外包含「已删除记录」工作表供管理员检查。**不同记录 ID 但库位/零件相同则仍保留、列入重复盘点待复核，不会错误累加。**

注意：如果电脑文件夹中含有早于删除操作导出的旧文件，同时缺少含有最新删除状态的新导出文件，电脑无法推断员工已经删除了什么。最后请务必收集每位同事的**最终完整导出文件**；如混合多个批次，请分文件夹独立汇总。

## 测试方法

```powershell
py -m unittest discover -s tests -v
node --check app.js
py -m py_compile desktop/stockcount.py
```

真实 iPhone / Android 的手势操作和 IndexedDB 离线更新还应在生产使用前现场验收。
