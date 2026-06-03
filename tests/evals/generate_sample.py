from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas  # pip install reportlab


def make_sample_pdf(filename="sample.pdf"):
    c = canvas.Canvas(filename, pagesize=letter)
    c.drawString(100, 700, "REMITTANCE ADVICE — Target Corp")
    c.drawString(100, 670, "PO Number: PO-8821")
    c.drawString(100, 650, "Deduction Code: SS")
    c.drawString(100, 630, "Deduction Amount: $240.00")
    c.drawString(100, 610, "Reason: Short shipment — units not received")
    c.save()


make_sample_pdf()
