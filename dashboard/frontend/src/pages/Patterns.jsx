import React, { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';

const Patterns = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/patterns');
        if (!response.ok) throw new Error('Failed to fetch patterns');
        const result = await response.json();
        setData(result);
      } catch (err) {
        setError('Failed to load patterns. Is the API server running?');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  // Process heatmap data into a grid structure
  const heatmapGrid = useMemo(() => {
    if (!data?.error_heatmap?.length) return null;

    const categories = [...new Set(data.error_heatmap.map(h => h.category))];
    const phases = [...new Set(data.error_heatmap.map(h => h.build_phase))];
    const maxCount = Math.max(...data.error_heatmap.map(h => h.count));

    // Create a lookup map
    const lookup = {};
    data.error_heatmap.forEach(h => {
      lookup[`${h.category}|${h.build_phase}`] = h;
    });

    return { categories, phases, lookup, maxCount };
  }, [data]);

  const getHeatmapIntensity = (count, maxCount) => {
    if (!count || !maxCount) return 0;
    return Math.min(count / maxCount, 1);
  };

  const getRateClass = (rate) => {
    if (rate > 0.7) return 'rate-high';
    if (rate > 0.4) return 'rate-medium';
    return 'rate-low';
  };

  if (loading) {
    return <div className="page loading">Loading patterns...</div>;
  }

  if (error) {
    return (
      <div className="page">
        <nav className="page-nav">
          <Link to="/" className="nav-link">Runs</Link>
          <span className="nav-current">Patterns</span>
        </nav>
        <div className="error-banner">{error}</div>
      </div>
    );
  }

  return (
    <div className="patterns-page">
      {/* Navigation */}
      <nav className="page-nav">
        <Link to="/" className="nav-link">Runs</Link>
        <span className="nav-current">Patterns</span>
      </nav>

      <header className="page-header">
        <h1>Cross-Run Patterns</h1>
      </header>

      {/* Error Category Heatmap */}
      <section className="section">
        <h2 className="section-title">Error Category Heatmap</h2>
        {heatmapGrid ? (
          <div className="heatmap-container">
            <table className="heatmap-table">
              <thead>
                <tr>
                  <th>Category</th>
                  {heatmapGrid.phases.map(phase => (
                    <th key={phase}>{phase}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmapGrid.categories.map(category => (
                  <tr key={category}>
                    <td className="heatmap-category">{category}</td>
                    {heatmapGrid.phases.map(phase => {
                      const cell = heatmapGrid.lookup[`${category}|${phase}`];
                      const intensity = getHeatmapIntensity(cell?.count, heatmapGrid.maxCount);
                      return (
                        <td
                          key={phase}
                          className="heatmap-cell"
                          style={{
                            backgroundColor: cell?.count
                              ? `rgba(248, 81, 73, ${0.1 + intensity * 0.6})`
                              : 'transparent'
                          }}
                        >
                          {cell ? (
                            <div className="heatmap-cell-content">
                              <span className="heatmap-count">{cell.count}</span>
                              {(cell.architectural > 0 || cell.implementation > 0) && (
                                <div className="heatmap-split">
                                  {cell.architectural > 0 && (
                                    <span className="split-arch" title="Architectural">
                                      {cell.architectural}
                                    </span>
                                  )}
                                  {cell.implementation > 0 && (
                                    <span className="split-impl" title="Implementation">
                                      {cell.implementation}
                                    </span>
                                  )}
                                </div>
                              )}
                            </div>
                          ) : (
                            <span className="heatmap-empty">-</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="no-data">No failure data available</div>
        )}
      </section>

      {/* Top Failure Patterns */}
      <section className="section">
        <h2 className="section-title">Top Failure Patterns</h2>
        {data?.top_patterns?.length > 0 ? (
          <div className="patterns-list">
            {data.top_patterns.map((pattern, i) => (
              <div key={i} className="pattern-card">
                <div className="pattern-header">
                  <span className="pattern-name">{pattern.pattern}</span>
                  <span className="pattern-count">{pattern.total_occurrences} occurrences</span>
                </div>
                <div className="pattern-stats">
                  <div className="pattern-bar">
                    {pattern.architectural_count > 0 && (
                      <div
                        className="bar-segment architectural"
                        style={{
                          width: `${(pattern.architectural_count / pattern.total_occurrences) * 100}%`
                        }}
                        title={`Architectural: ${pattern.architectural_count}`}
                      />
                    )}
                    {pattern.implementation_count > 0 && (
                      <div
                        className="bar-segment implementation"
                        style={{
                          width: `${(pattern.implementation_count / pattern.total_occurrences) * 100}%`
                        }}
                        title={`Implementation: ${pattern.implementation_count}`}
                      />
                    )}
                    {(pattern.total_occurrences - pattern.architectural_count - pattern.implementation_count) > 0 && (
                      <div
                        className="bar-segment pending"
                        style={{
                          width: `${((pattern.total_occurrences - pattern.architectural_count - pattern.implementation_count) / pattern.total_occurrences) * 100}%`
                        }}
                        title="Pending classification"
                      />
                    )}
                  </div>
                  <div className="pattern-badges">
                    {pattern.architectural_count > 0 && (
                      <span className="badge-arch">{pattern.architectural_count} arch</span>
                    )}
                    {pattern.implementation_count > 0 && (
                      <span className="badge-impl">{pattern.implementation_count} impl</span>
                    )}
                  </div>
                </div>
                {pattern.example_run_ids?.length > 0 && (
                  <div className="pattern-examples">
                    <span className="examples-label">Examples:</span>
                    {pattern.example_run_ids.map((runId, j) => (
                      <Link key={j} to={`/runs/${runId}`} className="example-link">
                        {runId}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="no-data">No failure patterns found</div>
        )}
      </section>

      {/* Self-Correction Leaderboard */}
      <section className="section">
        <h2 className="section-title">Self-Correction Leaderboard</h2>
        {data?.self_correction?.length > 0 ? (
          <table className="leaderboard-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Total Retries</th>
                <th>Self-Corrected</th>
                <th>Failed</th>
                <th>Success Rate</th>
              </tr>
            </thead>
            <tbody>
              {data.self_correction.map((item, i) => (
                <tr key={i}>
                  <td>{item.category}</td>
                  <td>{item.total}</td>
                  <td className="count-success">{item.self_corrected}</td>
                  <td className="count-fail">{item.failed}</td>
                  <td className={getRateClass(item.rate)}>
                    {(item.rate * 100).toFixed(0)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="no-data">No retry data available</div>
        )}
      </section>

      {/* Tool Comparison */}
      <section className="section">
        <h2 className="section-title">Tool Comparison</h2>
        {data?.tool_comparison?.length > 1 ? (
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Tool Config</th>
                <th>Runs</th>
                <th>Avg Success</th>
                <th>Total Retries</th>
                <th>Architectural</th>
                <th>Implementation</th>
              </tr>
            </thead>
            <tbody>
              {data.tool_comparison.map((item, i) => (
                <tr key={i}>
                  <td className="tool-config">{item.tool_config}</td>
                  <td>{item.run_count}</td>
                  <td className={getRateClass(item.avg_success_rate)}>
                    {(item.avg_success_rate * 100).toFixed(0)}%
                  </td>
                  <td>{item.total_retries}</td>
                  <td className="count-arch">{item.architectural_count}</td>
                  <td className="count-impl">{item.implementation_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : data?.tool_comparison?.length === 1 ? (
          <div className="single-tool-note">
            <p>All runs used the same tool configuration:</p>
            <code>{data.tool_comparison[0].tool_config}</code>
          </div>
        ) : (
          <div className="no-data">No tool configuration data available</div>
        )}
      </section>
    </div>
  );
};

export default Patterns;
