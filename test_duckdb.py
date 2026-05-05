import pandas as pd
import duckdb

df = pd.read_csv('/home/jyao/ADEO/services/ait-icarus/pandas-ai/emirati_employees_data.csv')
conn = duckdb.connect()
conn.register('my_table', df)

sql = """
SELECT "English Name"
FROM my_table
WHERE LOWER("English Name") LIKE '%mar%'
"""

result = conn.execute(sql).fetchdf()
print("LIKE '%mar%' matched:", len(result), "rows")

sql2 = """
SELECT "English Name"
FROM my_table
WHERE jaro_winkler_similarity(LOWER("English Name"), 'mari') > 0.85
"""

result2 = conn.execute(sql2).fetchdf()
print("Jaro Winkler matched:", len(result2), "rows")
