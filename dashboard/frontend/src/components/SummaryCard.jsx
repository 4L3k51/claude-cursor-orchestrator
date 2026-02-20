import React from 'react';

const SummaryCard = ({ title, value, accent, subtitle }) => {
  return (
    <div className={`summary-card summary-card-${accent}`}>
      <div className="summary-card-value">{value}</div>
      <div className="summary-card-title">{title}</div>
      {subtitle && <div className="summary-card-subtitle">{subtitle}</div>}
    </div>
  );
};

export default SummaryCard;
