import openpyxl

wb = openpyxl.load_workbook('resultats/evaluation-copilote/comparaison_ES_vs_logiciel.xlsx', data_only=True)
ws = wb['Résumé']

for row in ws.iter_rows(values_only=True):
    if row[0]:
        print(f"{row[0]}: {row[1]}")
