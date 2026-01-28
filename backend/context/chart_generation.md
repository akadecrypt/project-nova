# Data Visualization Guidelines

## IMPORTANT: Do NOT Generate Chart URLs

Do NOT attempt to generate QuickChart.io URLs or any image-based charts. They are error-prone and often fail to render.

## Instead: Use Well-Formatted Tables

When users ask for charts, graphs, or visualizations, provide the data in a **well-formatted markdown table** with a clear summary.

### Example Response for "Show me a chart of bucket growth"

**api-request-logs** - Growth over the last 2 weeks:

| Date | Size (GB) | Objects (M) | Daily Growth |
|------|-----------|-------------|--------------|
| Jan 13 | 185.2 | 42.5 | - |
| Jan 15 | 188.5 | 43.2 | +1.8% |
| Jan 17 | 191.8 | 43.9 | +1.8% |
| Jan 19 | 195.0 | 44.6 | +1.7% |
| Jan 21 | 198.2 | 45.3 | +1.6% |
| Jan 23 | 201.5 | 46.0 | +1.7% |
| Jan 25 | 204.8 | 46.7 | +1.6% |
| Jan 27 | 208.0 | 47.4 | +1.6% |

**Summary:** The bucket grew from 185.2 GB to 208.0 GB (+12.3%) over 2 weeks, with ~1.6 GB average daily growth. Object count increased from 42.5M to 47.4M (+11.5%).

## Guidelines

1. **Always use tables** - they render reliably and look good
2. **Add a text summary** - highlight key insights, trends, percentages
3. **Include calculated fields** - growth rates, percentages, comparisons
4. **Keep it readable** - round numbers, use appropriate units (GB, M, K)
5. **Answer the user's question** - if they want trends, explain the trend

## For Comparisons

Use tables with clear headers:

| Object Store | Total Size | Used | Free | Usage % |
|--------------|------------|------|------|---------|
| oss1 | 10 TB | 3.2 TB | 6.8 TB | 32% |
| oss3 | 10 TB | 5.1 TB | 4.9 TB | 51% |

**Insight:** oss3 has 60% more data than oss1 and is approaching 50% capacity.

## For Distributions

| Bucket | Size | % of Total |
|--------|------|------------|
| api-request-logs | 208 GB | 45% |
| user-uploads | 156 GB | 34% |
| backups | 95 GB | 21% |

The tables will render beautifully in the UI and are much more reliable than charts.
