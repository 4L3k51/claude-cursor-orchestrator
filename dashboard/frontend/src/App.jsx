import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import RunList from './pages/RunList';
import RunDetail from './pages/RunDetail';
import Patterns from './pages/Patterns';

function App() {
  return (
    <Router>
      <div className="app">
        <Routes>
          <Route path="/" element={<RunList />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/patterns" element={<Patterns />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
