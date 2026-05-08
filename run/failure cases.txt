{
  "conversation_id": "081c1970-f0da-4f1b-a030-69c51413fe8a",
  "query": "whatis the employee id of ayesha",
  "output_type": "string",
  "column_selection_enabled": true,
  "column_selection_threshold": 30,
  "column_values_budget_ratio": 0.10
}

{
    "response": "Employee Ayesha Jumaa Mubarak Al Qubaisi has Employee ID: 111",
    "type": "string",
    "last_code_executed": "import pandas as pd\ndf = execute_sql_query(\"\"\"\n    SELECT \n        \"[Employee Master[Employee Name]]\" as employee_name,\n        \"[Employee Master[Employee Number]]\" as employee_id\n    FROM enterprise_data \n    WHERE \"[Employee Master[Employee Name]]\" ILIKE '%Ayesha%'\n\"\"\")\nif len(df) == 0:\n    result = {'type': 'string', 'value': 'No employee named Ayesha was found in the system.'}\nelse:\n    employee_name = df.iloc[0]['employee_name']\n    employee_id = df.iloc[0]['employee_id']\n    result = {'type': 'string', 'value': f'Employee {employee_name} has Employee ID: {employee_id}'}",
    "selected_columns": [
        "[Employee Master[Employee Name]]",
        "[Employee Master[Employee Number]]"
    ]
}


wrong because employee id has leading 0 and this one missed 0111

{
  "conversation_id": "081c1970-f0da-4f1b-a030-69c51413fe8a",
  "query": "what is the percetage by different leave types did ayesha take?",
  "output_type": "string",
  "column_selection_enabled": true,
  "column_selection_threshold": 30,
  "column_values_budget_ratio": 0.10
}

{
    "response": "Leave distribution for Ayesha Jumaa Mubarak Al Qubaisi (Total: 159 days):\nNon-Mandatory Leave: 22.64% (36 days)\nRemote Work: 35.85% (57 days)\nTraining Leave: 9.43% (15 days)\nWellbeing: 32.08% (51 days)",
    "type": "string",
    "last_code_executed": "import pandas as pd\ndf_employee = execute_sql_query(\"\"\"\n    SELECT \"[Employee Master[Employee Name]]\" as employee_name\n    FROM enterprise_data \n    WHERE \"[Employee Master[Employee Name]]\" ILIKE '%Ayesha%'\n\"\"\")\nif len(df_employee) == 0:\n    result = {'type': 'string', 'value': 'No employee named Ayesha was found in the system.'}\nelse:\n    df_leave = execute_sql_query(f\"\"\"\n        SELECT \n            rec['Employee Leave Details[Leave Type]'] as leave_type,\n            rec['Employee Leave Details[Leave Duration (Days)]'] as leave_duration\n        FROM enterprise_data \n        CROSS JOIN UNNEST(\"[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]\") AS t(rec)\n        WHERE \"[Employee Master[Employee Name]]\" ILIKE '%Ayesha%'\n    \"\"\")\n    if len(df_leave) == 0:\n        result = {'type': 'string', 'value': 'Employee Ayesha was found but has no leave records in the system.'}\n    else:\n        df_leave['leave_duration'] = pd.to_numeric(df_leave['leave_duration'], errors='coerce')\n        df_leave = df_leave.dropna(subset=['leave_duration'])\n        total_days = df_leave['leave_duration'].sum()\n        if total_days == 0 or len(df_leave) == 0:\n            result = {'type': 'string', 'value': 'Employee Ayesha has no leave records to calculate percentages from.'}\n        else:\n            leave_stats = df_leave.groupby('leave_type').agg(total_days=('leave_duration', 'sum'), count=('leave_duration', 'count')).reset_index()\n            leave_stats['percentage'] = round(leave_stats['total_days'] / total_days * 100, 2)\n            percentage_lines = []\n            for _, row in leave_stats.iterrows():\n                pct = row['percentage']\n                days = int(row['total_days'])\n                type_name = row['leave_type']\n                percentage_lines.append(f'{type_name}: {pct}% ({days} days)')\n            result = {'type': 'string', 'value': f\"\"\"Leave distribution for {df_employee.iloc[0]['employee_name']} (Total: {int(total_days)} days):\n\"\"\" + '\\n'.join(percentage_lines)}",
    "selected_columns": [
        "[Employee Master[Employee Name]]",
        "Employee Leave Details[Leave Type]",
        "Employee Leave Details[Leave Duration (Days)]"
    ]
}

{
  "conversation_id": "081c1970-f0da-4f1b-a030-69c51413fe8a",
  "query": "what is the percetage by different leave types did ayesha take? use the leave detail column",
  "output_type": "string",
  "column_selection_enabled": true,
  "column_selection_threshold": 30,
  "column_values_budget_ratio": 0.10
}

{
    "response": "Employee Ayesha Jumaa Mubarak Al Qubaisi was found, but no leave details columns were found in the database.",
    "type": "string",
    "last_code_executed": "import pandas as pd\nimport re\ndf_employee = execute_sql_query(\"\"\"\n    SELECT \"[Employee Master[Employee Name]]\" as employee_name\n    FROM enterprise_data \n    WHERE \"[Employee Master[Employee Name]]\" ILIKE '%Ayesha%'\n\"\"\")\nif len(df_employee) == 0:\n    result = {'type': 'string', 'value': 'No employee named Ayesha was found in the system.'}\nelse:\n    ayesha_name = df_employee.iloc[0]['employee_name']\n    df_columns = execute_sql_query(\"\"\"\n        DESCRIBE enterprise_data\n    \"\"\")\n    leave_columns = []\n    for idx, row in df_columns.iterrows():\n        col_name = row['column_name']\n        if 'leave' in col_name.lower() or 'Leave' in col_name:\n            leave_columns.append(col_name)\n    if len(leave_columns) == 0:\n        result = {'type': 'string', 'value': f'Employee {ayesha_name} was found, but no leave details columns were found in the database.'}\n    else:\n        found_data = False\n        for leave_col in leave_columns:\n            try:\n                df_leave = execute_sql_query(f\"\"\"\n                    SELECT \n                        rec['Leave Type'] as leave_type,\n                        rec['Leave Duration (Days)'] as leave_duration\n                    FROM enterprise_data \n                    CROSS JOIN UNNEST({leave_col}) AS t(rec)\n                    WHERE \"[Employee Master[Employee Name]]\" ILIKE '%Ayesha%'\n                \"\"\")\n                if len(df_leave) > 0:\n                    found_data = True\n                    break\n            except Exception:\n                continue\n        if not found_data or len(df_leave) == 0:\n            result = {'type': 'string', 'value': f'Employee {ayesha_name} was found but has no leave records in the system.'}\n        else:\n            df_leave['leave_duration'] = pd.to_numeric(df_leave['leave_duration'], errors='coerce')\n            df_leave = df_leave.dropna(subset=['leave_duration'])\n            total_days = df_leave['leave_duration'].sum()\n            if pd.isna(total_days) or total_days == 0 or len(df_leave) == 0:\n                result = {'type': 'string', 'value': f'Employee {ayesha_name} has no leave records to calculate percentages from.'}\n            else:\n                leave_stats = df_leave.groupby('leave_type').agg(total_days=('leave_duration', 'sum'), count=('leave_duration', 'count')).reset_index()\n                leave_stats['percentage'] = (leave_stats['total_days'] / total_days * 100).round(2)\n                percentage_lines = []\n                for _, row in leave_stats.iterrows():\n                    pct = row['percentage']\n                    days = int(row['total_days'])\n                    type_name = row['leave_type']\n                    percentage_lines.append(f'{type_name}: {pct}% ({days} days)')\n                result = {'type': 'string', 'value': f\"\"\"Leave distribution for {ayesha_name} (Total: {int(total_days)} days):\n\"\"\" + '\\n'.join(percentage_lines)}",
    "selected_columns": [
        "[Employee Master[Employee Name]]",
        "[Employee Leave Details[Leave Type]]",
        "[Employee Leave Details[Leave Duration (Days)]]"
    ]
}

{
  "conversation_id": "081c1970-f0da-4f1b-a030-69c51413fe8a",
  "query": "what is the percetage by different leave types did ayesha take? use the employee leave detail columns",
  "output_type": "string",
  "column_selection_enabled": true,
  "column_selection_threshold": 30,
  "column_values_budget_ratio": 0.10
}

{
    "response": "Leave distribution for Ayesha Jumaa Mubarak Al Qubaisi (Total: 159 days):\nNon-Mandatory Leave: 22.64% (36 days)\nRemote Work: 35.85% (57 days)\nTraining Leave: 9.43% (15 days)\nWellbeing: 32.08% (51 days)",
    "type": "string",
    "last_code_executed": "import pandas as pd\ndf_employee = execute_sql_query(\"\"\"\n    SELECT \"[Employee Master[Employee Name]]\" as employee_name\n    FROM enterprise_data \n    WHERE \"[Employee Master[Employee Name]]\" ILIKE '%Ayesha%'\n\"\"\")\nif len(df_employee) == 0:\n    result = {'type': 'string', 'value': 'No employee named Ayesha was found in the system.'}\nelse:\n    ayesha_name = df_employee.iloc[0]['employee_name']\n    df_leave = execute_sql_query(\"\"\"\n        SELECT \n            rec['Employee Leave Details[Leave Type]'] as leave_type,\n            rec['Employee Leave Details[Leave Duration (Days)]'] as leave_duration\n        FROM enterprise_data \n        CROSS JOIN UNNEST(\"[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]\") AS t(rec)\n        WHERE \"[Employee Master[Employee Name]]\" ILIKE '%Ayesha%'\n    \"\"\")\n    if len(df_leave) == 0:\n        result = {'type': 'string', 'value': f'Employee {ayesha_name} was found but has no leave records in the system.'}\n    else:\n        df_leave['leave_duration'] = pd.to_numeric(df_leave['leave_duration'], errors='coerce')\n        df_leave = df_leave.dropna(subset=['leave_duration'])\n        total_days = df_leave['leave_duration'].sum()\n        if pd.isna(total_days) or total_days == 0 or len(df_leave) == 0:\n            result = {'type': 'string', 'value': f'Employee {ayesha_name} has no leave records to calculate percentages from.'}\n        else:\n            leave_stats = df_leave.groupby('leave_type').agg(total_days=('leave_duration', 'sum')).reset_index()\n            leave_stats['percentage'] = round(leave_stats['total_days'] / total_days * 100, 2)\n            percentage_lines = []\n            for _, row in leave_stats.iterrows():\n                pct = row['percentage']\n                days = int(row['total_days'])\n                type_name = row['leave_type']\n                percentage_lines.append(f'{type_name}: {pct}% ({days} days)')\n            result = {'type': 'string', 'value': f\"\"\"Leave distribution for {ayesha_name} (Total: {int(total_days)} days):\n\"\"\" + '\\n'.join(percentage_lines)}",
    "selected_columns": [
        "[Employee Master[Employee Name]]",
        "Employee Leave Details[Leave Type]",
        "Employee Leave Details[Leave Duration (Days)]"
    ]
}

wrong it feels like the llm is not able to intelligently identify which columns should be used based on the collumn description sample vales etc.

