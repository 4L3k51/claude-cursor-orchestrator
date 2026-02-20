import React from 'react';

const ClassificationBar = ({ classifications }) => {
  if (!classifications) return <span className="text-muted">-</span>;

  const { architectural = 0, implementation = 0, clean_pass = 0, ambiguous = 0, pending = 0 } = classifications;
  const total = architectural + implementation + clean_pass + ambiguous + pending;

  if (total === 0) return <span className="text-muted">-</span>;

  const archPct = (architectural / total) * 100;
  const implPct = (implementation / total) * 100;
  const cleanPct = (clean_pass / total) * 100;
  const pendingPct = ((ambiguous + pending) / total) * 100;

  return (
    <div className="classification-bar-container">
      <div className="classification-bar">
        {archPct > 0 && (
          <div
            className="classification-bar-segment architectural"
            style={{ width: `${archPct}%` }}
            title={`Architectural: ${architectural}`}
          />
        )}
        {implPct > 0 && (
          <div
            className="classification-bar-segment implementation"
            style={{ width: `${implPct}%` }}
            title={`Implementation: ${implementation}`}
          />
        )}
        {cleanPct > 0 && (
          <div
            className="classification-bar-segment clean"
            style={{ width: `${cleanPct}%` }}
            title={`Clean: ${clean_pass}`}
          />
        )}
        {pendingPct > 0 && (
          <div
            className="classification-bar-segment pending"
            style={{ width: `${pendingPct}%` }}
            title={`Pending: ${ambiguous + pending}`}
          />
        )}
      </div>
      <div className="classification-counts">
        {architectural > 0 && <span className="count-arch">{architectural}</span>}
        {implementation > 0 && <span className="count-impl">{implementation}</span>}
        {clean_pass > 0 && <span className="count-clean">{clean_pass}</span>}
        {(ambiguous + pending) > 0 && <span className="count-pending">{ambiguous + pending}</span>}
      </div>
    </div>
  );
};

export default ClassificationBar;
