import os
import subprocess
import html
import re

md_path = os.path.abspath("docs/relatorio_extracao_tradingfloors.md")
html_path = os.path.abspath("docs/relatorio_temp.html")
pdf_path = os.path.abspath("docs/relatorio_extracao_tradingfloors.pdf")

with open(md_path, "r", encoding="utf-8") as f:
    content = f.read()

def md_to_html(md_text):
    lines = md_text.split("\n")
    html_lines = []
    in_table = False
    in_code = False
    is_mermaid = False
    code_block = []
    table_rows = []

    for line in lines:
        stripped = line.strip()

        # Blocos de código / Mermaid
        if stripped.startswith("```"):
            if in_code:
                in_code = False
                if is_mermaid:
                    # Renderiza diagrama arquitetural visual limpo
                    flow_html = """
                    <div class="arch-card">
                      <div class="arch-grid">
                        <div class="arch-node arch-source">
                          <div class="arch-tag">Origem dos Dados</div>
                          <div class="arch-name">Supabase TradingFloors</div>
                          <div class="arch-desc">PostgreSQL / REST API + Auth JWT</div>
                        </div>
                        <div class="arch-connector">➔</div>
                        <div class="arch-node arch-core">
                          <div class="arch-tag">Módulo Central</div>
                          <div class="arch-name">client_tf.py</div>
                          <div class="arch-desc">Sync Histórico & Polling 5s</div>
                        </div>
                        <div class="arch-connector">➔</div>
                        <div class="arch-targets">
                          <div class="target-box">
                            <span class="t-icon">💾</span>
                            <div><strong>SQLite Local (backtest_cache.db)</strong>: 2.266 operações em cache para simulações instantâneas.</div>
                          </div>
                          <div class="target-box">
                            <span class="t-icon">⚡</span>
                            <div><strong>Robô MT5 (MT5Bridge)</strong>: Execução automática e dimensionamento de lote.</div>
                          </div>
                          <div class="target-box">
                            <span class="t-icon">🧠</span>
                            <div><strong>Google TimesFM (IA 200M)</strong>: Inferência de probabilidade e cones de projeção.</div>
                          </div>
                          <div class="target-box">
                            <span class="t-icon">🌐</span>
                            <div><strong>Interface Web Suite</strong>: Dashboard, Backtest, Screeners e Base Estratégica.</div>
                          </div>
                        </div>
                      </div>
                    </div>
                    """
                    html_lines.append(flow_html)
                    is_mermaid = False
                else:
                    code_text = html.escape("\n".join(code_block))
                    html_lines.append(f'<pre class="code-box"><code>{code_text}</code></pre>')
                code_block = []
            else:
                in_code = True
                is_mermaid = "mermaid" in stripped
                code_block = []
            continue

        if in_code:
            code_block.append(line)
            continue

        # Tabelas Markdown
        if stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
                table_rows = []
            
            if re.match(r"^\|(\s*:?-+:?\s*\|)+$", stripped):
                continue
            
            cols = [c.strip() for c in stripped[1:-1].split("|")]
            table_rows.append(cols)
            continue
        else:
            if in_table:
                in_table = False
                t_html = ['<div class="table-container"><table>']
                if table_rows:
                    t_html.append("<thead><tr>")
                    for col in table_rows[0]:
                        col_fmt = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", col)
                        t_html.append(f"<th>{col_fmt}</th>")
                    t_html.append("</tr></thead><tbody>")
                    for row in table_rows[1:]:
                        t_html.append("<tr>")
                        for col in row:
                            col_fmt = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", col)
                            col_fmt = re.sub(r"`(.*?)`", r"<code>\1</code>", col_fmt)
                            t_html.append(f"<td>{col_fmt}</td>")
                        t_html.append("</tr>")
                    t_html.append("</tbody>")
                t_html.append("</table></div>")
                html_lines.append("".join(t_html))
                table_rows = []

        # Títulos
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            html_lines.append(f'<h1 class="main-title">{title}</h1>')
            continue
        elif stripped.startswith("## "):
            title = stripped[3:].strip()
            html_lines.append(f'<h2 class="sec-title">{title}</h2>')
            continue
        elif stripped.startswith("### "):
            title = stripped[4:].strip()
            html_lines.append(f'<h3 class="subsec-title">{title}</h3>')
            continue

        # Linha horizontal
        if stripped == "---":
            html_lines.append('<hr class="divider">')
            continue

        # Alertas GitHub (> [!NOTE], > [!IMPORTANT])
        if stripped.startswith("> [!IMPORTANT]") or stripped.startswith("> [!NOTE]"):
            alert_type = "important" if "IMPORTANT" in stripped else "note"
            alert_title = "IMPORTANTE" if alert_type == "important" else "OBSERVAÇÃO"
            html_lines.append(f'<div class="alert alert-{alert_type}"><div class="alert-title">ℹ️ {alert_title}</div>')
            continue
        elif stripped.startswith(">"):
            txt = stripped[1:].strip()
            txt = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", txt)
            html_lines.append(f'<p class="alert-body">{txt}</p></div>')
            continue

        # Listas
        if stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s+", stripped):
            item = re.sub(r"^(\*|\-|\d+\.)\s+", "", stripped)
            item = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", item)
            item = re.sub(r"`(.*?)`", r"<code>\1</code>", item)
            item = re.sub(r"\[(.*?)\]\(.*?\)", r"<strong>\1</strong>", item)
            html_lines.append(f'<li class="list-item">{item}</li>')
            continue

        # Parágrafos
        if stripped:
            para = stripped
            para = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", para)
            para = re.sub(r"`(.*?)`", r"<code>\1</code>", para)
            para = re.sub(r"\[(.*?)\]\(.*?\)", r"<strong>\1</strong>", para)
            html_lines.append(f'<p class="para">{para}</p>')
        else:
            html_lines.append('<div class="spacer"></div>')

    return "\n".join(html_lines)

body_html = md_to_html(content)

full_html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Relatório Técnico: Extração Integral de Trades da TradingFloors</title>
  <style>
    @page {{
      size: A4;
      margin: 18mm 14mm 18mm 14mm;
      @bottom-right {{
        content: counter(page) " / " counter(pages);
        font-size: 8pt;
        color: #64748b;
      }}
    }}
    
    * {{
      box-sizing: border-box;
      -webkit-print-color-adjust: exact !important;
      print-color-adjust: exact !important;
    }}
    
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      font-size: 10pt;
      line-height: 1.55;
      color: #1e293b;
      background: #ffffff;
      margin: 0;
      padding: 0;
    }}

    .header-branding {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 2px solid #0284c7;
      padding-bottom: 8px;
      margin-bottom: 20px;
    }}

    .branding-logo {{
      font-weight: 800;
      font-size: 11pt;
      color: #0f172a;
      letter-spacing: -0.5px;
    }}

    .branding-logo span {{
      color: #0284c7;
    }}

    .branding-meta {{
      font-size: 8pt;
      color: #64748b;
      font-weight: 500;
    }}

    .main-title {{
      font-size: 18pt;
      font-weight: 800;
      color: #0f172a;
      margin: 0 0 12px 0;
      line-height: 1.25;
      letter-spacing: -0.5px;
    }}

    .sec-title {{
      font-size: 13pt;
      font-weight: 700;
      color: #0f172a;
      margin: 22px 0 10px 0;
      padding-bottom: 5px;
      border-bottom: 1px solid #e2e8f0;
      page-break-after: avoid;
    }}

    .subsec-title {{
      font-size: 11pt;
      font-weight: 700;
      color: #0369a1;
      margin: 16px 0 8px 0;
      page-break-after: avoid;
    }}

    .para {{
      margin: 0 0 10px 0;
      color: #334155;
      text-align: justify;
    }}

    .divider {{
      border: none;
      border-top: 1px dashed #cbd5e1;
      margin: 18px 0;
    }}

    .spacer {{
      height: 4px;
    }}

    .list-item {{
      margin-bottom: 6px;
      color: #334155;
      line-height: 1.5;
    }}

    code {{
      font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
      font-size: 8.5pt;
      background: #f1f5f9;
      color: #0f172a;
      padding: 1px 5px;
      border-radius: 4px;
      border: 1px solid #e2e8f0;
    }}

    .code-box {{
      background: #0f172a;
      color: #f8fafc;
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 8pt;
      line-height: 1.45;
      overflow-x: auto;
      margin: 10px 0 14px 0;
      border: 1px solid #1e293b;
      page-break-inside: avoid;
    }}

    .code-box code {{
      background: transparent;
      color: #38bdf8;
      border: none;
      padding: 0;
    }}

    .alert {{
      border-left: 4px solid #0284c7;
      background: #f0f9ff;
      padding: 10px 14px;
      border-radius: 4px;
      margin: 14px 0;
      page-break-inside: avoid;
    }}

    .alert-important {{
      border-left-color: #f59e0b;
      background: #fffbeb;
    }}

    .alert-title {{
      font-weight: 700;
      font-size: 9pt;
      color: #92400e;
      margin-bottom: 4px;
    }}

    .alert-note .alert-title {{
      color: #0369a1;
    }}

    .alert-body {{
      margin: 0;
      font-size: 9pt;
      color: #475569;
      line-height: 1.45;
    }}

    .table-container {{
      margin: 12px 0 18px 0;
      page-break-inside: avoid;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 8.5pt;
      text-align: left;
    }}

    th {{
      background: #f8fafc;
      color: #0f172a;
      font-weight: 700;
      padding: 7px 8px;
      border-bottom: 2px solid #cbd5e1;
      border-top: 1px solid #e2e8f0;
    }}

    td {{
      padding: 6px 8px;
      border-bottom: 1px solid #e2e8f0;
      color: #334155;
    }}

    tr:nth-child(even) td {{
      background: #f8fafc;
    }}

    .arch-card {{
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      padding: 14px;
      margin: 14px 0 18px 0;
      page-break-inside: avoid;
    }}

    .arch-grid {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .arch-node {{
      background: #ffffff;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      padding: 10px;
      flex: 1;
      text-align: center;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}

    .arch-tag {{
      font-size: 7pt;
      text-transform: uppercase;
      font-weight: 700;
      color: #0284c7;
      margin-bottom: 3px;
    }}

    .arch-name {{
      font-weight: 800;
      font-size: 9pt;
      color: #0f172a;
    }}

    .arch-desc {{
      font-size: 7.5pt;
      color: #64748b;
      margin-top: 2px;
    }}

    .arch-connector {{
      font-size: 14pt;
      color: #0284c7;
      font-weight: bold;
    }}

    .arch-targets {{
      flex: 1.8;
      display: flex;
      flex-direction: column;
      gap: 5px;
    }}

    .target-box {{
      display: flex;
      align-items: center;
      gap: 6px;
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 4px;
      padding: 5px 8px;
      font-size: 7.5pt;
      color: #334155;
    }}

    .t-icon {{
      font-size: 9pt;
    }}

    .footer-note {{
      margin-top: 30px;
      padding-top: 10px;
      border-top: 1px solid #e2e8f0;
      font-size: 7.5pt;
      color: #94a3b8;
      display: flex;
      justify-content: space-between;
    }}
  </style>
</head>
<body>

  <div class="header-branding">
    <div class="branding-logo">TRADINGFLOORS <span>AUTOMATION SUITE</span></div>
    <div class="branding-meta">Documento Técnico Oficial | Base Histórica Consolidada</div>
  </div>

  {body_html}

  <div class="footer-note">
    <span>TradingFloors MT5 Automation Suite • Suporte Quantitativo & Backtesting</span>
    <span>Gerado em 14/09/2026 • Confidencial e Pessoal</span>
  </div>

</body>
</html>
"""

with open(html_path, "w", encoding="utf-8") as f:
    f.write(full_html)

chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(chrome_path):
    chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

cmd = [
    chrome_path,
    "--headless",
    "--disable-gpu",
    "--no-pdf-header-footer",
    f"--print-to-pdf={pdf_path}",
    html_path
]

res = subprocess.run(cmd, capture_output=True, text=True)
print("Execução Chrome headless código:", res.returncode)

if os.path.exists(pdf_path):
    size_kb = os.path.getsize(pdf_path) / 1024
    print(f"PDF gerado com sucesso em: {pdf_path} ({size_kb:.1f} KB)")
else:
    print("Falha ao gerar PDF:", res.stderr)
