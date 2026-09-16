import openpyxl
wb = openpyxl.load_workbook(r'E:\zhuanhuan\output\errorlog.xlsx')
ws = wb.active
for row in ws.iter_rows(values_only=True):
    if any(cell for cell in row):
        print(list(row))
