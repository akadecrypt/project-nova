# Chart Generation Guidelines

When users ask for visual representations like charts or graphs, use QuickChart.io to generate them.

## QuickChart URL Format

```
https://quickchart.io/chart?c={CHART_CONFIG}
```

Where `{CHART_CONFIG}` is a **URL-encoded** JSON object.

## Important Rules

1. **Always URL-encode** the entire chart configuration JSON
2. **Keep charts simple** - avoid complex nested options
3. **Use short labels** - dates should be "Jan 13" not "2026-01-13"
4. **Limit data points** - max 10-12 points for readability
5. **Test the JSON** is valid before encoding

## Simple Line Chart Example

For a line chart showing bucket growth:

```json
{
  "type": "line",
  "data": {
    "labels": ["Jan 13", "Jan 15", "Jan 17", "Jan 19", "Jan 21", "Jan 23", "Jan 25", "Jan 27"],
    "datasets": [{
      "label": "Size (GB)",
      "data": [185, 189, 192, 195, 198, 202, 205, 208],
      "borderColor": "#007bff",
      "fill": false
    }]
  }
}
```

Encoded URL:
```
![Chart](https://quickchart.io/chart?c=%7B%22type%22%3A%22line%22%2C%22data%22%3A%7B%22labels%22%3A%5B%22Jan%2013%22%2C%22Jan%2015%22%2C%22Jan%2017%22%2C%22Jan%2019%22%2C%22Jan%2021%22%2C%22Jan%2023%22%2C%22Jan%2025%22%2C%22Jan%2027%22%5D%2C%22datasets%22%3A%5B%7B%22label%22%3A%22Size%20(GB)%22%2C%22data%22%3A%5B185%2C189%2C192%2C195%2C198%2C202%2C205%2C208%5D%2C%22borderColor%22%3A%22%23007bff%22%2C%22fill%22%3Afalse%7D%5D%7D%7D)
```

## Simple Bar Chart Example

```json
{
  "type": "bar",
  "data": {
    "labels": ["bucket-a", "bucket-b", "bucket-c"],
    "datasets": [{
      "label": "Objects",
      "data": [1500, 2300, 800],
      "backgroundColor": ["#007bff", "#00c851", "#ff9800"]
    }]
  }
}
```

## Pie Chart Example

```json
{
  "type": "pie",
  "data": {
    "labels": ["bucket-a", "bucket-b", "bucket-c"],
    "datasets": [{
      "data": [45, 35, 20],
      "backgroundColor": ["#007bff", "#00c851", "#ff9800"]
    }]
  }
}
```

## When to Use Charts

- User explicitly asks for a "chart", "graph", or "visualization"
- Showing trends over time (line chart)
- Comparing sizes/counts between items (bar chart)
- Showing distribution/percentages (pie chart)

## When NOT to Use Charts

- Simple queries - just return tables or text
- Single data points - no need for a chart
- When data is not available - say so instead of making up data

## Alternative: Describe Data

If chart generation is too complex, you can describe the data in text:

"The bucket has grown steadily from 185 GB on Jan 13 to 208 GB on Jan 27, an increase of about 12%."
