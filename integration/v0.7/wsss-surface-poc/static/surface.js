(() => {
  'use strict';
  const empty = { type: 'FeatureCollection', features: [] };
  const styleUrl = new URLSearchParams(location.search).get('style') || 'https://demotiles.maplibre.org/style.json';
  const map = new maplibregl.Map({
    container: 'map',
    style: styleUrl,
    center: [103.995, 1.35],
    zoom: 13.5,
    attributionControl: true,
  });
  map.addControl(new maplibregl.NavigationControl(), 'top-right');

  function makeXImage(size = 72) {
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, size, size);
    ctx.strokeStyle = '#ff3f4b'; ctx.lineWidth = 14; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(14, 14); ctx.lineTo(size - 14, size - 14); ctx.moveTo(size - 14, 14); ctx.lineTo(14, size - 14); ctx.stroke();
    ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(14, 14); ctx.lineTo(size - 14, size - 14); ctx.moveTo(size - 14, 14); ctx.lineTo(14, size - 14); ctx.stroke();
    return ctx.getImageData(0, 0, size, size);
  }

  function addSourcesAndLayers() {
    if (!map.hasImage('closure-x')) map.addImage('closure-x', makeXImage(), { pixelRatio: 2 });
    map.addSource('odss-surface', { type: 'geojson', data: empty });
    map.addSource('odss-overlays', { type: 'geojson', data: empty });
    map.addLayer({ id:'surface-runways', type:'line', source:'odss-surface', filter:['==',['get','aeroway'],'runway'], paint:{'line-color':'#27333e','line-width':16,'line-opacity':.92} });
    map.addLayer({ id:'surface-taxiways', type:'line', source:'odss-surface', filter:['==',['get','aeroway'],'taxiway'], paint:{'line-color':'#f4c347','line-width':5,'line-opacity':.88} });
    map.addLayer({ id:'surface-taxilanes', type:'line', source:'odss-surface', filter:['==',['get','aeroway'],'taxilane'], paint:{'line-color':'#7fc8ff','line-width':3,'line-opacity':.75} });
    map.addLayer({ id:'surface-labels', type:'symbol', source:'odss-surface', filter:['all',['has','ref'],['in',['get','aeroway'],['literal',['taxiway','taxilane','runway']]]], layout:{'symbol-placement':'line','text-field':['get','ref'],'text-size':12,'text-allow-overlap':false}, paint:{'text-color':'#0a1520','text-halo-color':'#ffffff','text-halo-width':2} });
    map.addLayer({ id:'overlay-lines', type:'line', source:'odss-overlays', filter:['==',['get','symbol'],'surface-overlay-line'], paint:{'line-color':['case',['==',['get','operational_state'],'closed'],'#ff3f4b','#f2a93b'],'line-width':10,'line-opacity':['case',['boolean',['get','display'],true],.95,.18]} });
    map.addLayer({ id:'overlay-junctions', type:'circle', source:'odss-overlays', filter:['==',['get','symbol'],'included-junction'], paint:{'circle-radius':8,'circle-color':'#ff3f4b','circle-stroke-width':3,'circle-stroke-color':'#ffffff'} });
    map.addLayer({ id:'overlay-x', type:'symbol', source:'odss-overlays', filter:['==',['get','symbol'],'closure-x'], layout:{'icon-image':'closure-x','icon-size':.65,'icon-allow-overlap':true}, paint:{'icon-opacity':['case',['boolean',['get','display'],true],1,.2]} });

    ['overlay-lines','overlay-junctions','overlay-x'].forEach(id => {
      map.on('click', id, event => {
        const feature = event.features && event.features[0];
        if (!feature) return;
        const p = feature.properties || {};
        new maplibregl.Popup({ closeButton:true })
          .setLngLat(event.lngLat)
          .setHTML(`<strong>${p.notam_id || 'NOTAM'} · ${p.surface_ref || ''}</strong><br>${p.operational_state || ''}<br>Confidence: ${p.match_confidence || ''}<br>${p.match_method || ''}`)
          .addTo(map);
      });
      map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
    });
  }

  function fitContract(contract) {
    const bbox = contract.geometry_source && contract.geometry_source.bbox;
    if (bbox) map.fitBounds([[bbox.west,bbox.south],[bbox.east,bbox.north]], { padding:45, duration:500 });
  }

  function renderFindings(contract) {
    const host = document.getElementById('findings');
    host.textContent = '';
    (contract.findings || []).forEach(finding => {
      const card = document.createElement('article');
      card.className = `finding ${finding.clause.operation} ${finding.mapped ? '' : 'unmapped'}`;
      card.innerHTML = `<h2>${finding.clause.target_ref} · ${finding.clause.operation.toUpperCase()}</h2>
        <p>${finding.reason}</p><p>Geometry: ${finding.mapped ? finding.confidence : 'not mapped'} · Applicability: ${finding.applicability}</p>`;
      host.appendChild(card);
    });
  }

  async function loadGeometry() {
    const response = await fetch('/v1/airports/WSSS/surface-geometry');
    if (!response.ok) throw new Error((await response.json()).detail || `HTTP ${response.status}`);
    const contract = await response.json();
    map.getSource('odss-surface').setData(contract.surface_geojson || empty);
    fitContract(contract);
  }

  async function resolve() {
    const status = document.getElementById('status');
    status.textContent = 'Resolving NOTAM against the versioned WSSS surface graph…';
    try {
      const local = document.getElementById('briefing-time').value;
      const body = {
        notam_text: document.getElementById('notam').value,
        briefing_time_utc: local ? `${local}:00Z` : null,
        aircraft_code: document.getElementById('aircraft-code').value || null,
        include_surface_geometry: true,
      };
      const response = await fetch('/v1/airports/WSSS/surface-resolve', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
      const contract = await response.json();
      if (!response.ok) throw new Error(contract.detail || `HTTP ${response.status}`);
      map.getSource('odss-surface').setData(contract.surface_geojson || empty);
      map.getSource('odss-overlays').setData(contract.notam_overlays_geojson || empty);
      fitContract(contract);
      renderFindings(contract);
      const mapped = (contract.findings || []).filter(item => item.mapped).length;
      status.textContent = `${mapped}/${(contract.findings || []).length} clauses mapped. Original NOTAM remains authoritative.`;
    } catch (error) {
      status.textContent = error.message;
    }
  }

  map.on('load', async () => {
    addSourcesAndLayers();
    try { await loadGeometry(); } catch (error) { document.getElementById('status').textContent = error.message; }
    document.getElementById('resolve').addEventListener('click', resolve);
  });
})();
