import * as THREE from 'three';

// Native geometry: one shared scene language, no external model downloads.
export function createCampus(canvas, { replay = false } = {}) {
  if (!canvas) return null;
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); }
  catch { canvas.hidden = true; canvas.insertAdjacentHTML('afterend', '<p class="scene-caption">Thiết bị chưa hỗ trợ 3D. Bạn vẫn có thể đọc giải thích và xem bảng phân bổ bên dưới.</p>'); return null; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.6));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, .1, 100);
  camera.position.set(10, 9, 13); camera.lookAt(0, .4, 0);
  const root = new THREE.Group(); scene.add(root);
  scene.add(new THREE.HemisphereLight(0xe9faff, 0x7f9aba, 3));
  const sun = new THREE.DirectionalLight(0xfff3df, 4); sun.position.set(-5, 10, 6); scene.add(sun);
  const material = color => new THREE.MeshStandardMaterial({ color, roughness: .68, metalness: .03 });
  const colors = { blue: material(0x72b7e9), navy: material(0x2468a0), cream: material(0xffedcf), white: material(0xffffff), mint: material(0x8acbb5), peach: material(0xf5b59c), ink: material(0x223d55), gold: material(0xf0c36a) };
  function mesh(geometry, mat, parent, x = 0, y = 0, z = 0) {
    const value = new THREE.Mesh(geometry, mat); value.position.set(x, y, z); parent.add(value); return value;
  }
  function block(parent, x, y, z, w, h, d, mat) { return mesh(new THREE.BoxGeometry(w, h, d), mat, parent, x, y, z); }
  function ball(parent, x, y, z, radius, mat) { return mesh(new THREE.SphereGeometry(radius, 20, 16), mat, parent, x, y, z); }
  function character(x, z, supervisor = false, color = colors.blue) {
    const figure = new THREE.Group(); figure.position.set(x, .18, z); root.add(figure);
    mesh(new THREE.CapsuleGeometry(.25, .3, 6, 16), color, figure, 0, .5, 0);
    ball(figure, 0, 1.05, 0, .32, colors.cream);
    for (const eye of [-.11, .11]) ball(figure, eye, 1.08, .289, .035, colors.ink);
    const smile = mesh(new THREE.TorusGeometry(.075, .012, 6, 12, Math.PI), colors.ink, figure, 0, .99, .305); smile.rotation.z = Math.PI;
    for (const side of [-1, 1]) {
      ball(figure, side * .27, .55, .05, .105, colors.cream);
      mesh(new THREE.CapsuleGeometry(.085, .16, 4, 10), colors.navy, figure, side * .12, .12, .05);
    }
    if (supervisor) {
      block(figure, .18, .5, .29, .26, .33, .06, colors.gold);
      for (const eye of [-.11, .11]) mesh(new THREE.TorusGeometry(.072, .013, 6, 18), colors.navy, figure, eye, 1.08, .31);
    } else {
      mesh(new THREE.CylinderGeometry(.25, .25, .1, 20), colors.navy, figure, 0, 1.34, 0);
      const hat = block(figure, 0, 1.4, 0, .65, .06, .65, colors.navy); hat.rotation.y = Math.PI / 4;
      ball(figure, .31, 1.29, .24, .045, colors.gold);
    }
    return figure;
  }
  mesh(new THREE.CylinderGeometry(4.2, 3.9, .42, 80), colors.blue, root, 0, -.28, 0);
  mesh(new THREE.CylinderGeometry(3.98, 4.08, .12, 80), colors.mint, root, 0, -.02, 0);
  mesh(new THREE.CylinderGeometry(2.55, 2.55, .035, 64), colors.cream, root, 0, .06, 0);
  const actors = [];
  let active = null, target = new THREE.Vector3(), currentTarget = new THREE.Vector3(), elapsed = 0;
  if (!replay) {
    const building = new THREE.Group(); building.position.set(0, 0, -1.2); root.add(building);
    block(building, 0, 1.1, 0, 3, 2.1, 1.5, colors.white);
    block(building, 0, 2.22, 0, 3.3, .22, 1.8, colors.navy);
    const roof = mesh(new THREE.CylinderGeometry(1.15, 1.15, .35, 3), colors.blue, building, 0, 2.5, .35); roof.rotation.set(Math.PI / 2, Math.PI / 2, 0); roof.scale.set(1.7, .8, 1);
    for (const x of [-1, -.5, .5, 1]) { block(building, x, 1.4, .77, .3, .6, .035, colors.blue); block(building, x, .6, .77, .3, .55, .035, colors.blue); }
    block(building, 0, .45, .8, .4, .85, .06, colors.navy);
    for (const x of [-3, 3]) {
      mesh(new THREE.CylinderGeometry(.1, .15, 1.2, 10), colors.cream, root, x, .6, -1.1);
      ball(root, x, 1.45, -1.1, .7, colors.mint); ball(root, x + .2, 1.7, -1.2, .45, colors.mint);
    }
    actors.push(character(-1.25, 1.6), character(1.2, 1.4, true, colors.peach), character(-2.7, .3, false, colors.gold));
    // Clouds and books float as a single composed landing interaction.
    for (const [x, y, z] of [[-3.4, 3, -.5], [2.7, 3.5, -1.8]]) {
      const cloud = new THREE.Group(); root.add(cloud); cloud.position.set(x, y, z);
      ball(cloud, 0, 0, 0, .42, colors.white); ball(cloud, .4, -.08, 0, .3, colors.white); ball(cloud, -.35, -.1, 0, .29, colors.white); actors.push(cloud);
    }
  } else {
    active = character(-2.6, 1.3); target.copy(active.position); currentTarget.copy(target);
  }
  const advisorNodes = new Map();
  function label(text, x, z) {
    const surface = document.createElement('canvas'); surface.width = 512; surface.height = 80;
    const context = surface.getContext('2d'); context.fillStyle = '#163d5a'; context.textAlign = 'center'; context.font = '700 25px Manrope, sans-serif'; context.fillText(text, 256, 45, 500);
    const texture = new THREE.CanvasTexture(surface);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false }));
    sprite.position.set(x, 2.2, z); sprite.scale.set(2.8, .44, 1); root.add(sprite); return sprite;
  }
  function update(decision, registry = [], names = [], step = 0, capacities = []) {
    if (!replay) return;
    // At most six stations visible; active supervisor is always among them.
    const ids = registry.filter((id, index) => (decision?.capacities || capacities)[index] > 0).slice(0, 6);
    if (decision?.advisor_id && !ids.includes(decision.advisor_id)) ids[ids.length - 1] = decision.advisor_id;
    for (const [id, entry] of advisorNodes) if (!ids.includes(id)) { root.remove(entry.figure, entry.label); dispose(entry.figure); dispose(entry.label); advisorNodes.delete(id); }
    ids.forEach((id, index) => {
      const x = (ids.length < 3 ? index - (ids.length - 1) / 2 : index % 3 - 1) * 2.5, z = index < 3 ? -1.8 : .5;
      let entry = advisorNodes.get(id);
      if (!entry) { entry = { figure: character(x, z, true, index % 2 ? colors.peach : colors.blue), label: label(names[registry.indexOf(id)] || id, x, z) }; advisorNodes.set(id, entry); }
      entry.figure.position.set(x, .18, z); entry.label.position.set(x, 2.2, z);
      const i = registry.indexOf(id), capacity = decision?.capacities?.[i] || 0, load = decision?.loads_after?.[i] || 0;
      entry.figure.scale.setScalar(id === decision?.advisor_id ? 1.15 : .9);
      entry.label.material.opacity = capacity && load >= capacity ? .55 : 1;
    });
    const destination = advisorNodes.get(decision?.advisor_id)?.figure.position;
    target.set(destination?.x ?? -2.6, .18, destination ? destination.z + 1 : 1.3);
    active.visible = true;
    if (step === 0 || paused) { active.position.copy(target); currentTarget.copy(target); draw(); }
  }
  let paused = matchMedia('(prefers-reduced-motion: reduce)').matches, visible = true, frame, previous = 0;
  let pointerX = 0, pointerY = 0;
  function draw() { renderer.render(scene, camera); }
  function resize() {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height, false); camera.aspect = width / height;
    camera.position.set(10, 9, 13).multiplyScalar((width < 400 ? 1.2 : 1) * (replay ? .76 : 1)); camera.lookAt(0, .4, 0); camera.updateProjectionMatrix(); draw();
  }
  const observer = new ResizeObserver(resize); observer.observe(canvas);
  function schedule() {
    if (paused || !visible || document.hidden) {
      cancelAnimationFrame(frame);
      frame = undefined;
      previous = 0;
    } else if (frame === undefined) {
      frame = requestAnimationFrame(tick);
    }
  }
  const intersection = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; schedule(); }); intersection.observe(canvas);
  function tick(time) {
    frame = undefined;
    if (paused || !visible || document.hidden) return;
    const dt = previous ? Math.min((time - previous) / 1000, .05) : 0;
    previous = time;
    elapsed += dt;
    root.rotation.y += (pointerX * .16 - root.rotation.y) * .04;
    root.rotation.x += (pointerY * .03 - root.rotation.x) * .04;
    if (!replay) actors.forEach((actor, index) => { actor.position.y = (index < 3 ? .18 : index === 3 ? 3 : 3.5) + Math.sin(elapsed * 1.2 + index) * .07; });
    if (active) { currentTarget.lerp(target, Math.min(dt * 4, 1)); active.position.copy(currentTarget); active.position.y += Math.sin(elapsed * 9) * .035; }
    draw();
    schedule();
  }
  const pointer = event => { const rect = canvas.getBoundingClientRect(); pointerX = (event.clientX - rect.left) / rect.width - .5; pointerY = (event.clientY - rect.top) / rect.height - .5; };
  document.addEventListener('visibilitychange', schedule);
  canvas.addEventListener('pointermove', pointer); resize(); schedule();
  function dispose(object) { object.traverse(value => { value.geometry?.dispose(); if (value.material?.map) value.material.map.dispose(); if (value.material && !Object.values(colors).includes(value.material)) value.material.dispose(); }); }
  return { update, get paused() { return paused; }, toggle() { paused = !paused; draw(); schedule(); return paused; }, destroy() { cancelAnimationFrame(frame); observer.disconnect(); intersection.disconnect(); document.removeEventListener('visibilitychange', schedule); canvas.removeEventListener('pointermove', pointer); dispose(root); Object.values(colors).forEach(value => value.dispose()); renderer.dispose(); } };
}
