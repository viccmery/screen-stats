const CONDITIONS = ['W1118', '9047', '23129', '33300', 'anosmic'];
const COLORS = { W1118: '#263b32', '9047': '#e88d54', '23129': '#68b4ce', '33300': '#9b85d3', anosmic: '#6bbb8d' };
const METRICS = {
  n_holes: { label: 'Holes per video', short: 'holes', format: v => Math.round(v).toLocaleString(), axis: v => Math.round(v) },
  median_max_size: { label: 'Median maximum size', short: 'px²', format: v => Math.round(v).toLocaleString() + ' px²', axis: v => Math.round(v / 1000) + 'k' },
  median_lifetime: { label: 'Median lifetime', short: 'frames', format: v => Math.round(v) + ' frames', axis: v => Math.round(v) }
};

let videos = [], summaries = [], comparisons = [], overall = [], excluded = [];
let metric = 'n_holes', activeConditions = new Set(CONDITIONS), sort = { key: 'condition', direction: 1 };

function parseCSV(text) {
  const rows = []; let row = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i], next = text[i + 1];
    if (c === '"' && quoted && next === '"') { field += '"'; i++; }
    else if (c === '"') quoted = !quoted;
    else if (c === ',' && !quoted) { row.push(field); field = ''; }
    else if ((c === '\n' || c === '\r') && !quoted) {
      if (c === '\r' && next === '\n') i++;
      row.push(field); if (row.some(Boolean)) rows.push(row); row = []; field = '';
    } else field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const headers = rows.shift();
  return rows.map(values => Object.fromEntries(headers.map((h, i) => [h, coerce(values[i])] )));
}
function coerce(value) {
  if (value === 'True') return true; if (value === 'False') return false;
  if (value !== '' && value != null && !Number.isNaN(Number(value))) return Number(value);
  return value;
}

async function loadData() {
  const files = ['video_summary', 'group_summary', 'stats_vs_W1118', 'overall_stats', 'unclassified_files'];
  const responses = await Promise.all(files.map(name => fetch(`../results/${name}.csv`)));
  if (responses.some(r => !r.ok)) throw new Error('Could not load analysis CSV files.');
  [videos, summaries, comparisons, overall, excluded] = await Promise.all(responses.map(r => r.text().then(parseCSV)));
}

function renderFilters() {
  const root = document.querySelector('#conditionFilters'); root.innerHTML = '';
  CONDITIONS.forEach(condition => {
    const button = document.createElement('button');
    button.textContent = condition; button.className = activeConditions.has(condition) ? 'active' : '';
    button.onclick = () => {
      if (activeConditions.has(condition) && activeConditions.size > 1) activeConditions.delete(condition); else activeConditions.add(condition);
      renderFilters(); renderChart();
    };
    root.append(button);
  });
}

function quantile(values, q) {
  const sorted = [...values].sort((a,b) => a-b), pos = (sorted.length - 1) * q, base = Math.floor(pos), rest = pos - base;
  return sorted[base + 1] === undefined ? sorted[base] : sorted[base] + rest * (sorted[base + 1] - sorted[base]);
}
function niceMax(value) { const pow = 10 ** Math.floor(Math.log10(value)); return Math.ceil(value / pow) * pow; }

function renderChart() {
  const root = document.querySelector('#chart');
  const shown = CONDITIONS.filter(c => activeConditions.has(c));
  const allValues = videos.filter(v => shown.includes(v.condition)).map(v => v[metric]);
  const max = niceMax(Math.max(...allValues) * 1.08), width = 760, height = 320, pad = {t:18,r:18,b:42,l:55};
  const plotW = width-pad.l-pad.r, plotH=height-pad.t-pad.b, y=v => pad.t + plotH - (v/max)*plotH;
  const x = i => pad.l + plotW * ((i + .5) / shown.length);
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${METRICS[metric].label} by condition">`;
  for (let i=0;i<=4;i++){const value=max*i/4, yp=y(value);svg+=`<line class="grid-line" x1="${pad.l}" y1="${yp}" x2="${width-pad.r}" y2="${yp}"/><text class="axis-label" x="${pad.l-10}" y="${yp+3}" text-anchor="end">${METRICS[metric].axis(value)}</text>`}
  shown.forEach((condition, ci) => {
    const vals=videos.filter(v=>v.condition===condition).map(v=>v[metric]), cx=x(ci), spread=Math.min(27,plotW/shown.length*.22);
    const q1=quantile(vals,.25), med=quantile(vals,.5), q3=quantile(vals,.75);
    svg+=`<line class="iqr-line" x1="${cx}" y1="${y(q1)}" x2="${cx}" y2="${y(q3)}"/><line class="median-line" x1="${cx-13}" y1="${y(med)}" x2="${cx+13}" y2="${y(med)}"/>`;
    vals.forEach((v,vi)=>{const jitter=((vi*37)%17/16-.5)*spread*2;svg+=`<circle class="data-dot" data-condition="${condition}" data-value="${v}" cx="${cx+jitter}" cy="${y(v)}" r="5" fill="${COLORS[condition]}" opacity=".84"/>`});
    svg+=`<text class="condition-label" x="${cx}" y="${height-13}" text-anchor="middle">${condition}</text>`;
  });
  svg+='</svg>'; root.innerHTML=svg;
  root.querySelectorAll('.data-dot').forEach(dot=>{
    dot.addEventListener('mouseenter',()=>showTooltip(dot)); dot.addEventListener('mouseleave',()=>root.querySelector('.chart-tooltip')?.remove());
  });
  renderInsights();
}
function showTooltip(dot) {
  const root=document.querySelector('#chart'), box=root.getBoundingClientRect(), circle=dot.getBoundingClientRect(), tip=document.createElement('div');
  tip.className='chart-tooltip';tip.innerHTML=`<strong>${dot.dataset.condition}</strong><br>${METRICS[metric].format(+dot.dataset.value)}`;
  tip.style.left=`${circle.left-box.left+circle.width/2}px`;tip.style.top=`${circle.top-box.top}px`;root.append(tip);
}

function pFormat(p) { return p < .001 ? p.toExponential(1) : p.toFixed(3); }
function renderInsights() {
  const test=overall.find(r=>r.metric===metric), rows=comparisons.filter(r=>r.metric===metric);
  document.querySelector('#insightPanel').innerHTML=`
    <div class="test-summary"><small>KRUSKAL–WALLIS</small><strong>p ${test.p_value < .001 ? '&lt; 0.001' : '= '+pFormat(test.p_value)}</strong><small>H = ${test.H.toFixed(2)} · ${test.p_value < .05 ? 'group effect detected' : 'no group effect'}</small></div>
    <div><h3>Against W1118</h3><div class="comparison-list">${rows.map(r=>`<div class="comparison-item"><strong>${r.condition}</strong><i class="sig-dot ${r.significant_0.05?'':'ns'}"></i><span>${r.median_difference>0?'+':''}${METRICS[metric].format(r.median_difference)}</span><small>p${r.p_holm<.001?' &lt; .001':' = '+pFormat(r.p_holm)}</small></div>`).join('')}</div></div>`;
}

function recordingDate(filename) { const m=filename.match(/analysis_(\d{4})-(\d{2})-(\d{2})/); return m ? `${m[3]}/${m[2]}/${m[1].slice(2)}` : '—'; }
function shortName(filename) { const pc=filename.match(/(pc\d+)/)?.[1] || ''; return filename.split('_hole_analysis')[0] + (pc ? ` · ${pc}` : ''); }
function renderTable() {
  const query=document.querySelector('#searchInput').value.toLowerCase();
  const filtered=videos.filter(v=>`${v.condition} ${v.video_file}`.toLowerCase().includes(query)).sort((a,b)=>{
    const av=a[sort.key],bv=b[sort.key]; return (typeof av==='number'?av-bv:String(av).localeCompare(String(bv)))*sort.direction;
  });
  document.querySelector('#videoTable').innerHTML=filtered.map((v)=>`<tr data-file="${encodeURIComponent(v.video_file)}"><td><span class="condition-badge"><i style="background:${COLORS[v.condition]}"></i>${v.condition}</span></td><td><div class="file-name" title="${v.video_file}">${shortName(v.video_file)}</div></td><td>${v.n_holes}</td><td>${Math.round(v.median_max_size).toLocaleString()} px²</td><td>${Math.round(v.median_lifetime)} frames</td><td class="date-cell">${recordingDate(v.video_file)}</td></tr>`).join('');
  document.querySelector('#rowCount').textContent=`Showing ${filtered.length} of ${videos.length} videos`;
  document.querySelectorAll('#videoTable tr').forEach(row=>row.onclick=()=>showDetail(videos.find(v=>v.video_file===decodeURIComponent(row.dataset.file))));
}
function showDetail(v) {
  document.querySelector('#dialogTitle').textContent=shortName(v.video_file);
  const fields=[['Condition',v.condition],['Unique holes',v.n_holes],['Rows analysed',v.n_rows.toLocaleString()],['Median max size',Math.round(v.median_max_size).toLocaleString()+' px²'],['Largest hole',Math.round(v.max_hole_size).toLocaleString()+' px²'],['Median lifetime',Math.round(v.median_lifetime)+' frames'],['Longest lifetime',Math.round(v.max_lifetime)+' frames']];
  document.querySelector('#dialogBody').innerHTML=fields.map(([label,value])=>`<div><strong>${value}</strong><span>${label}</span></div>`).join('')+`<div class="dialog-path"><strong>${v.video_file}</strong><span>Source filename</span></div>`;
  document.querySelector('#detailDialog').showModal();
}
function renderQuality() {
  const grouped = excluded.reduce((acc,item)=>{const key=item.reason;acc[key]=(acc[key]||0)+1;return acc;},{});
  document.querySelector('#qualityList').innerHTML=Object.entries(grouped).map(([reason,count])=>`<div class="quality-item"><span>!</span><div><strong>${count} file${count>1?'s':''}</strong><small>${reason}</small></div></div>`).join('');
}
function exportView() {
  const rows=videos.filter(v=>activeConditions.has(v.condition)), cols=['condition','video_file','n_holes','median_max_size','median_lifetime'];
  const csv=[cols.join(','),...rows.map(r=>cols.map(c=>`"${String(r[c]).replaceAll('"','""')}"`).join(','))].join('\n');
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download=`sensory-screen-${metric}.csv`;a.click();URL.revokeObjectURL(a.href);showToast(`Exported ${rows.length} videos`);
}
function showToast(message){const el=document.querySelector('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2200)}

function bindEvents() {
  document.querySelectorAll('#metricSwitch button').forEach(button=>button.onclick=()=>{document.querySelector('#metricSwitch .active').classList.remove('active');button.classList.add('active');metric=button.dataset.metric;renderChart()});
  document.querySelector('#searchInput').addEventListener('input',renderTable);
  document.querySelectorAll('th[data-sort]').forEach(th=>th.onclick=()=>{sort.direction=sort.key===th.dataset.sort?-sort.direction:1;sort.key=th.dataset.sort;renderTable()});
  document.querySelector('#detailDialog .dialog-close').onclick=()=>document.querySelector('#detailDialog').close();
  document.querySelector('#exportButton').onclick=exportView;
  document.querySelector('#themeToggle').onclick=()=>{const dark=document.documentElement.dataset.theme==='dark';document.documentElement.dataset.theme=dark?'':'dark';localStorage.setItem('screen-theme',dark?'light':'dark')};
  if(localStorage.getItem('screen-theme')==='dark')document.documentElement.dataset.theme='dark';
  const links=[...document.querySelectorAll('.nav-link')], sections=[...document.querySelectorAll('main section[id]')];
  new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){links.forEach(l=>l.classList.toggle('active',l.hash===`#${e.target.id}`))}}),{rootMargin:'-20% 0px -70%'}).observe?.(sections[0]);
  sections.slice(1).forEach(s=>new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting)links.forEach(l=>l.classList.toggle('active',l.hash===`#${e.target.id}`))}),{rootMargin:'-20% 0px -70%'}).observe(s));
}

loadData().then(()=>{document.querySelector('#videoCount').textContent=videos.length;renderFilters();renderChart();renderTable();renderQuality();bindEvents()}).catch(error=>{document.querySelector('#chart').innerHTML=`<p class="load-error">${error.message}<br>Serve the repository over HTTP to view the dashboard.</p>`;console.error(error)});
