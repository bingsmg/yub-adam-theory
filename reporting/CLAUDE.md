# reporting/ — 报告层

## 概述

将推荐结果格式化为多种输出：Rich 终端表格、带 Plotly 交互图表的 HTML 报告。

## 模块

### console.py — 终端输出

`print_recommendations(result: DailyRecommendation)`

使用 Rich 库渲染：
- 头部面板：日期、分析数量、信号数量
- 摘要表：代码、名称、条件标记(B/T/R)、风险(颜色编码)、止损
- 每个推荐的详细分析段落

### html_report.py — HTML 报告

`generate_html_report(result, output_path, open_browser=True) -> Path`

生成包含 5 个交互式 Plotly 图表的美观 HTML 报告：
1. **风险评分 + 止损百分比** — 条形图+散点
2. **质量 vs 风险** — 气泡散点图（象限分割线）
3. **成交量比** — 按正常/缩量/放量着色
4. **线索构成** — 条件出现次数饼图
5. **投影方向 + 收敛度** — 按方向着色

模板文件：`reporting/templates/report.html`（Jinja2 模板引擎渲染）

关键外部依赖：plotly (graph_objects, express), jinja2

## 使用示例

```python
from reporting.console import print_recommendations
from reporting.html_report import generate_html_report

# 终端输出
print_recommendations(result)

# HTML 报告（自动在浏览器打开）
html_path = generate_html_report(result)
```
