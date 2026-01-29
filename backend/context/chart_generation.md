# Data Visualization Guidelines

## Chart Generation

When users ask for charts, graphs, or visualizations, you can generate interactive charts using the following format:

### Chart JSON Format

Wrap chart data in a code block with the `chart` language identifier:

````
```chart
{
  "type": "bar",
  "title": "Chart Title",
  "labels": ["Label1", "Label2", "Label3"],
  "datasets": [
    {
      "label": "Dataset Name",
      "data": [10, 20, 30]
    }
  ]
}
```
````

### Supported Chart Types

1. **bar** - Bar chart (default)
2. **line** - Line chart
3. **pie** - Pie chart
4. **doughnut** - Doughnut chart

### Chart Data Structure

```json
{
  "type": "bar|line|pie|doughnut",
  "title": "Optional chart title",
  "labels": ["Category1", "Category2", ...],
  "datasets": [
    {
      "label": "Dataset name",
      "data": [value1, value2, ...]
    }
  ]
}
```

---

## Example Charts

### Bar Chart - Error Count by Severity
```chart
{
  "type": "bar",
  "title": "Errors by Severity (Last 24h)",
  "labels": ["FATAL", "ERROR", "WARN"],
  "datasets": [
    {
      "label": "Count",
      "data": [5, 150, 320]
    }
  ]
}
```

### Line Chart - Error Trend
```chart
{
  "type": "line",
  "title": "Error Trend (Hourly)",
  "labels": ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
  "datasets": [
    {
      "label": "Errors",
      "data": [12, 8, 25, 18, 42, 15]
    }
  ]
}
```

### Pie Chart - Storage Distribution
```chart
{
  "type": "pie",
  "title": "Storage by Bucket",
  "labels": ["api-logs", "backups", "archives", "temp"],
  "datasets": [
    {
      "label": "Size (GB)",
      "data": [245, 180, 120, 55]
    }
  ]
}
```

### Multiple Datasets (Line)
```chart
{
  "type": "line",
  "title": "Errors vs Warnings",
  "labels": ["Mon", "Tue", "Wed", "Thu", "Fri"],
  "datasets": [
    {
      "label": "Errors",
      "data": [45, 32, 55, 28, 41]
    },
    {
      "label": "Warnings",
      "data": [120, 95, 140, 88, 110]
    }
  ]
}
```

---

## When to Use Charts

Generate charts when users ask for:
- "Show me a chart of..."
- "Graph the..."
- "Visualize..."
- "Plot..."
- "Show trend..."
- "Compare X and Y visually"

### Good Chart Use Cases:
1. **Error trends over time** - Line chart
2. **Error distribution by severity/type** - Bar or pie chart
3. **Storage usage by bucket** - Pie or bar chart
4. **Comparison between object stores** - Bar chart
5. **Node error counts** - Bar chart
6. **Alert distribution** - Pie chart

---

## Chart + Table Combination

For comprehensive answers, provide BOTH a chart AND a summary table:

**Example Response:**

Here's the error distribution for the last 24 hours:

```chart
{
  "type": "bar",
  "title": "Errors by Component",
  "labels": ["OC", "MS", "Atlas", "Curator"],
  "datasets": [{"label": "Errors", "data": [89, 45, 23, 12]}]
}
```

| Component | Error Count | % of Total |
|-----------|-------------|------------|
| OC | 89 | 52.7% |
| MS | 45 | 26.6% |
| Atlas | 23 | 13.6% |
| Curator | 12 | 7.1% |

**Summary:** Object Controller (OC) has the most errors at 52.7%, followed by Metadata Service at 26.6%.

---

## Query Data for Charts

To generate charts, first query the data:

### Error by Severity
```sql
SELECT severity, COUNT(*) as count 
FROM logs 
WHERE timestamp > strftime('%s','now') - 86400 
GROUP BY severity 
ORDER BY count DESC
```

### Error by Component
```sql
SELECT pod, COUNT(*) as count 
FROM logs 
WHERE severity IN ('ERROR','FATAL') 
GROUP BY pod 
ORDER BY count DESC
```

### Hourly Error Trend
```sql
SELECT 
    strftime('%H:00', timestamp, 'unixepoch') as hour,
    COUNT(*) as errors
FROM logs 
WHERE severity IN ('ERROR','FATAL') 
AND timestamp > strftime('%s','now') - 86400
GROUP BY hour
ORDER BY hour
```

### Storage by Bucket
```sql
SELECT b.bucket_name, bs.size_gb 
FROM bucket_stats bs 
JOIN bucket b ON bs.bucket_id = b.bucket_id 
ORDER BY bs.size_gb DESC 
LIMIT 10
```

### Errors by Object Store
```sql
SELECT object_store_name, COUNT(*) as errors 
FROM logs 
WHERE severity IN ('ERROR','FATAL') 
AND object_store_name IS NOT NULL
GROUP BY object_store_name
```

---

## Important Guidelines

1. **Always query data first** - Use execute_sql to get real data before generating charts
2. **Use appropriate chart types** - Bar for comparisons, line for trends, pie for proportions
3. **Keep it simple** - Don't show more than 10 categories in a chart
4. **Include a summary** - Always explain what the chart shows
5. **Combine with tables** - Tables provide exact numbers, charts show patterns
6. **Title your charts** - Always include a descriptive title
