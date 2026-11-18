"""
PDF da venda para enviar ao cliente: o que foi comprado, o que já foi pago e o que está
em aberto (com a previsão de cada parcela). NUNCA inclui custo nem lucro.

`dados_pdf_venda` lê o banco; `renderizar` só desenha (recebe dados prontos).
"""
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .services import brl


def _data(d):
    return d.strftime("%d/%m/%Y")


def dados_pdf_venda(venda, emissor):
    """Reúne, em tipos simples, o que o PDF mostra (venda já carregada, do dono)."""
    hoje = timezone.localdate()
    itens = [
        {
            "nome": i.produto.nome,
            "qtd": i.quantidade,
            "unit": f"R$ {brl(i.preco_venda_praticado)}",
            "total": f"R$ {brl(i.total)}",
        }
        for i in venda.itens.all()
    ]
    pagamentos, proximo = [], None
    for p in venda.pagamentos.all():  # já ordenados por data
        if p.pago:
            estado, situacao = "pago", f"Pago em {_data(p.data)}"
        elif p.data < hoje:
            dias = (hoje - p.data).days
            estado = "atrasado"
            situacao = f"Venceu em {_data(p.data)} ({dias} dia{'s' if dias != 1 else ''} de atraso)"
        else:
            estado, situacao = "pendente", f"Vence em {_data(p.data)}"
        if estado != "pago" and proximo is None:
            proximo = (_data(p.data), f"R$ {brl(p.valor)}")
        pagamentos.append(
            {
                "meio": p.get_metodo_display(),
                "valor": f"R$ {brl(p.valor)}",
                "situacao": situacao,
                "estado": estado,
            }
        )
    resumo = venda.pagamentos_resumo()
    return {
        "emissor": emissor,
        "emitido_em": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
        "cliente": venda.cliente.nome,
        "data_venda": timezone.localtime(venda.data_venda).strftime("%d/%m/%Y"),
        "itens": itens,
        "total": f"R$ {brl(venda.total)}",
        "pagamentos": pagamentos,
        "pago": f"R$ {brl(resumo['pago'])}",
        "aberto": f"R$ {brl(resumo['pendente'])}",
        "atrasado": f"R$ {brl(resumo['atrasado'])}" if resumo["atrasado"] > 0 else None,
        "quitado": resumo["estado"] == "quitado",
        "proximo": proximo,
    }


# --------------------------------------------------------------------------
# Desenho
# --------------------------------------------------------------------------
VERDE = colors.HexColor("#198754")
AMARELO = colors.HexColor("#b58100")
VERMELHO = colors.HexColor("#dc3545")
CINZA = colors.HexColor("#6c757d")
CABECALHO = colors.HexColor("#212529")
LINHA = colors.HexColor("#dee2e6")


def _estilos():
    base = getSampleStyleSheet()["Normal"]
    n = ParagraphStyle("n", parent=base, fontName="Helvetica", fontSize=10, leading=13)
    return {
        "n": n,
        "pequeno": ParagraphStyle("p", parent=n, fontSize=8.5, leading=11, textColor=CINZA),
        "dir": ParagraphStyle("d", parent=n, alignment=TA_RIGHT),
        "titulo": ParagraphStyle("t", parent=n, fontName="Helvetica-Bold", fontSize=18, leading=22),
        "h": ParagraphStyle("h", parent=n, fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4),
        "th": ParagraphStyle("th", parent=n, fontName="Helvetica-Bold", textColor=colors.white),
        "thd": ParagraphStyle("thd", parent=n, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_RIGHT),
    }


def _p(texto, estilo):
    # Paragraph interpreta marcação: todo texto vindo do usuário passa por escape().
    return Paragraph(escape(str(texto)), estilo)


def renderizar(d):
    """Gera o PDF (bytes) a partir do dicionário de `dados_pdf_venda`."""
    s = _estilos()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Venda - {d['cliente']}", author=d["emissor"],
    )
    largura = A4[0] - 36 * mm
    el = []

    # Cabeçalho
    el.append(Paragraph("Resumo da compra", s["titulo"]))
    el.append(_p(f"Emitido por {d['emissor']} em {d['emitido_em']}", s["pequeno"]))
    el.append(Spacer(1, 6 * mm))
    ficha = Table(
        [[_p("Cliente", s["pequeno"]), _p("Data da compra", s["pequeno"])],
         [_p(d["cliente"], s["n"]), _p(d["data_venda"], s["n"])]],
        colWidths=[largura * 0.65, largura * 0.35],
    )
    ficha.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINHA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    el.append(ficha)

    # Itens
    el.append(Paragraph("Itens comprados", s["h"]))
    linhas = [[_p("Item", s["th"]), _p("Qtd.", s["thd"]), _p("Valor unit.", s["thd"]), _p("Total", s["thd"])]]
    for i in d["itens"]:
        linhas.append([_p(i["nome"], s["n"]), _p(i["qtd"], s["dir"]), _p(i["unit"], s["dir"]), _p(i["total"], s["dir"])])
    linhas.append(["", "", _p("Total da compra", s["dir"]), Paragraph(f"<b>{escape(d['total'])}</b>", s["dir"])])
    t = Table(linhas, colWidths=[largura * 0.50, largura * 0.12, largura * 0.19, largura * 0.19], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CABECALHO),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fa")]),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, LINHA),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, CABECALHO),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    el.append(t)

    # Situação dos pagamentos (resumo em destaque)
    el.append(Paragraph("Situação do pagamento", s["h"]))
    if d["quitado"]:
        destaque = Paragraph(f'<font color="{VERDE.hexval()}"><b>COMPRA QUITADA</b></font> - obrigado!', s["n"])
    else:
        texto = f'<b>Em aberto: {escape(d["aberto"])}</b>'
        if d["proximo"]:
            texto += f' &nbsp;·&nbsp; próximo vencimento: {escape(d["proximo"][0])} ({escape(d["proximo"][1])})'
        cor = VERMELHO if d["atrasado"] else AMARELO
        destaque = Paragraph(f'<font color="{cor.hexval()}">{texto}</font>', s["n"])
    resumo = Table(
        [[destaque],
         [Paragraph(f"Já pago: <b>{escape(d['pago'])}</b> &nbsp;·&nbsp; Em aberto: <b>{escape(d['aberto'])}</b>"
                    + (f' &nbsp;·&nbsp; <font color="{VERMELHO.hexval()}">Vencido: <b>{escape(d["atrasado"])}</b></font>' if d["atrasado"] else ""),
                    s["n"])]],
        colWidths=[largura],
    )
    resumo.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, VERDE if d["quitado"] else (VERMELHO if d["atrasado"] else AMARELO)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    el.append(resumo)
    el.append(Spacer(1, 4 * mm))

    # Cada pagamento / parcela
    linhas = [[_p("#", s["th"]), _p("Meio", s["th"]), _p("Valor", s["thd"]), _p("Situação", s["th"])]]
    cores = []
    for n, p in enumerate(d["pagamentos"], start=1):
        cor = {"pago": VERDE, "pendente": AMARELO, "atrasado": VERMELHO}[p["estado"]]
        cores.append(cor)
        linhas.append([
            _p(n, s["n"]), _p(p["meio"], s["n"]), _p(p["valor"], s["dir"]),
            Paragraph(f'<font color="{cor.hexval()}"><b>{escape(p["situacao"])}</b></font>', s["n"]),
        ])
    t = Table(linhas, colWidths=[largura * 0.08, largura * 0.27, largura * 0.20, largura * 0.45], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CABECALHO),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINHA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (3, 0), (3, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    el.append(t)

    el.append(Spacer(1, 8 * mm))
    el.append(Paragraph(
        "Este documento é apenas um resumo informativo da compra e não possui valor fiscal. "
        "Em caso de dúvida, fale com quem lhe vendeu.", s["pequeno"]))

    def rodape(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(CINZA)
        rotulo = f"{d['emissor']} - {d['cliente']}"
        canvas.drawString(18 * mm, 10 * mm, rotulo if len(rotulo) <= 80 else rotulo[:77] + "...")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(el, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
