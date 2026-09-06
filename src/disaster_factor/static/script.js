// Dashboard plotting scaffold: fetch computed static/points.json (with w/h), and draw SVG
// circle markers with simple <title> tooltips provided by the server-side transform.

console.log("dashboard loaded");

async function loadAndPlotPoints() {
  try {
    const img = document.querySelector('.map-image');
    if (!img) {
      console.warn('No element with .map-image found');
      return;
    }

    // Measure displayed size (w,h) in pixels
    const w = img.clientWidth;
    const h = img.clientHeight;

    // Fetch points.json from server with w/h so server can compute x/y
    const resp = await fetch(`points.json?w=${encodeURIComponent(w)}&h=${encodeURIComponent(h)}`);
    if (!resp.ok) {
      console.warn('Could not fetch points.json:', resp.status);
      return;
    }

    const data = await resp.json();
    const points = data.points || [];
    const config = data.config || {};

    // Ensure we have an SVG overlay in the container
    const container = img.parentElement;
    let svg = container.querySelector('svg.map-overlay');
    if (!svg) {
      svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.classList.add('map-overlay');
      svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      container.appendChild(svg);
      // Make svg absolutely positioned over the image via CSS
    }

    svg.setAttribute('width', w);
    svg.setAttribute('height', h);
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);

    // Clear any prior markers
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    points.forEach((pt) => {
      const { x, y, label, severity } = pt;
      if (typeof x !== 'number' || typeof y !== 'number') return;

      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', String(x));
      circle.setAttribute('cy', String(y));
      circle.setAttribute('r', '6');
      circle.classList.add('map-marker');
      if (severity) circle.classList.add(`sev-${severity}`);

      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = label || '';
      circle.appendChild(title);

      svg.appendChild(circle);
    });
  } catch (err) {
    console.error('Error loading/plotting points:', err);
  }
}

// Run once onload
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadAndPlotPoints);
} else {
  loadAndPlotPoints();
}
