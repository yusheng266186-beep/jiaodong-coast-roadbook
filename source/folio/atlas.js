(() => {
  const atlas = document.getElementById("route-atlas");
  const board = atlas.querySelector(".coast-map-board");
  const canvas = board.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const {window:[west, south, east, north], coast} = JSON.parse(document.getElementById("coast-data").textContent);
  const pins = new Map(Array.from(board.querySelectorAll("[data-stop]"), (pin) => [pin.dataset.stop, pin]));
  const legs = [["qingdao","weihai"],["weihai","yantai"],["yantai","penglai"]];

  function drawMap() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!ctx || !width || !height) return;
    const ratio = Math.min(2, devicePixelRatio || 1);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0);
    const project = ([lon, lat]) => [(lon - west) / (east - west) * width, (north - lat) / (north - south) * height];
    const sea = ctx.createLinearGradient(0, 0, width, height);
    sea.addColorStop(0, "#e0ebe4");
    sea.addColorStop(.65, "#c4dad5");
    sea.addColorStop(1, "#bbd3d0");
    ctx.fillStyle = sea;
    ctx.fillRect(0, 0, width, height);

    ctx.beginPath();
    for (const ring of coast) {
      ctx.moveTo(...project(ring[0]));
      for (const point of ring.slice(1)) ctx.lineTo(...project(point));
      ctx.closePath();
    }
    ctx.fillStyle = "#eee3c6";
    ctx.fill("evenodd");
    ctx.strokeStyle = "#678f82";
    ctx.lineWidth = .85;
    ctx.stroke();

    ctx.beginPath();
    for (let lon = Math.ceil(west); lon < east; lon++) {
      ctx.moveTo(...project([lon, north]));
      ctx.lineTo(...project([lon, south]));
    }
    for (let lat = Math.ceil(south); lat < north; lat++) {
      ctx.moveTo(...project([west, lat]));
      ctx.lineTo(...project([east, lat]));
    }
    ctx.lineWidth = .55;
    ctx.strokeStyle = "#456b5c38";
    ctx.stroke();

    const active = board.querySelector("[aria-current]")?.dataset.stop;
    const pinPoint = (key) => [pins.get(key).dataset.x / 100 * width, pins.get(key).dataset.y / 100 * height];
    ctx.lineCap = "round";
    for (const [from, to] of legs) {
      const emphasized = active === to;
      ctx.beginPath();
      ctx.moveTo(...pinPoint(from));
      ctx.lineTo(...pinPoint(to));
      ctx.setLineDash(to === "penglai" ? [2, 4] : [5, 4]);
      ctx.strokeStyle = emphasized ? "#a4412e" : "#46695c";
      ctx.lineWidth = emphasized ? 2.3 : 1.35;
      ctx.stroke();
    }
  }

  if (ctx) {
    drawMap();
    new MutationObserver(drawMap).observe(atlas, {attributeFilter:["data-active-day"]});
    if ("ResizeObserver" in window) new ResizeObserver(drawMap).observe(board);
    else window.addEventListener("resize", drawMap);
  }

  for (const clock of document.querySelectorAll("[data-clock]")) {
    const slider = clock.querySelector("input");
    const time = clock.querySelector("[data-clock-time]");
    const name = clock.querySelector("[data-clock-name]");
    const details = clock.querySelector("[data-clock-link]");
    const marks = Array.from(clock.querySelectorAll(".time-mark"), (node) => ({
      node, minute: Number(node.dataset.minute), stamp: node.dataset.stamp,
      name: node.dataset.name, event: node.dataset.event
    }));
    let selected = -1;

    function preview(index) {
      if (index === selected) return;
      marks[selected]?.node.removeAttribute("data-active");
      selected = index;
      const mark = marks[selected];
      mark.node.setAttribute("data-active", "");
      time.textContent = mark.stamp;
      time.dateTime = mark.stamp;
      name.textContent = mark.name;
      details.href = "#" + mark.event;
      details.setAttribute("aria-label", "展开" + mark.name);
      slider.setAttribute("aria-valuetext", mark.stamp + " " + mark.name);
    }

    slider.addEventListener("input", () => {
      let index = marks.findIndex((mark) => mark.minute >= slider.valueAsNumber);
      if (index < 0) index = marks.length - 1;
      const earlier = marks[index - 1];
      if (earlier && slider.valueAsNumber - earlier.minute < marks[index].minute - slider.valueAsNumber) index--;
      preview(index);
    });
    slider.addEventListener("change", () => { slider.value = marks[selected].minute; });
    slider.addEventListener("keydown", (event) => {
      const direction = {ArrowRight:1,ArrowUp:1,ArrowLeft:-1,ArrowDown:-1}[event.key];
      if (!direction || event.altKey || event.metaKey || event.ctrlKey) return;
      event.preventDefault();
      const index = Math.max(0, Math.min(marks.length - 1, selected + direction));
      slider.value = marks[index].minute;
      preview(index);
    });
    preview(0);
  }

  const track = document.getElementById("scene-track");
  const scenes = Array.from(track.children);
  const sceneCaption = document.querySelector(".scene-position");
  const sceneButtons = Array.from(document.querySelectorAll("[data-scene-step]"));
  const sceneOffset = (card) => card.offsetLeft - scenes[0].offsetLeft;
  let currentScene = 0;

  function syncSceneTrack() {
    const limit = track.scrollWidth - track.clientWidth;
    const offset = track.scrollLeft;
    if (limit < 2 || offset <= 1) currentScene = 0;
    else if (offset >= limit - 1) currentScene = scenes.length - 1;
    else currentScene = scenes.reduce((closest, card, index) =>
      Math.abs(sceneOffset(card) - offset) < Math.abs(sceneOffset(scenes[closest]) - offset) ? index : closest, 0
    );
    track.closest(".scenes").toggleAttribute("data-overflow", limit >= 2);
    track.tabIndex = limit >= 2 ? 0 : -1;
    sceneButtons[0].disabled = offset <= 1;
    sceneButtons[1].disabled = limit < 2 || offset >= limit - 1;
    const label = `${currentScene + 1} / ${scenes.length}`;
    if (sceneCaption.textContent !== label) sceneCaption.textContent = label;
  }

  for (const button of sceneButtons) {
    button.addEventListener("click", () => {
      const next = Math.min(scenes.length - 1, Math.max(0, currentScene + Number(button.dataset.sceneStep)));
      const reduced = document.documentElement.dataset.motion === "reduced"
        || matchMedia("(prefers-reduced-motion: reduce)").matches;
      track.scrollTo({left: sceneOffset(scenes[next]), behavior: reduced ? "instant" : "smooth"});
    });
  }
  track.addEventListener("scroll", syncSceneTrack, {passive:true});
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(syncSceneTrack).observe(track);
  syncSceneTrack();

  const viewer = document.getElementById("image-viewer");
  if (typeof viewer.showModal !== "function") return;
  const sheet = viewer.querySelector(".viewer-picture");
  const picture = sheet.querySelector("img");
  const title = document.getElementById("viewer-title");
  const count = document.getElementById("viewer-count");
  const source = document.getElementById("viewer-source");
  const close = viewer.querySelector(".viewer-close");
  const frames = Array.from(document.querySelectorAll("figure[data-art]"));
  const buttons = Array.from(viewer.querySelectorAll("[data-viewer-step]"));
  let group = [];
  let index = 0;
  let opener;
  let gesture;

  function show(next) {
    index = Math.max(0, Math.min(next, group.length - 1));
    const frame = group[index];
    const art = frame.querySelector("img");
    title.textContent = frame.dataset.artTitle;
    count.textContent = index + 1 + " / " + group.length;
    buttons[0].disabled = index === 0;
    buttons[1].disabled = index === group.length - 1;
    count.parentElement.hidden = group.length === 1;
    const credit = frame.querySelector(".image-source");
    source.href = credit.href;
    source.textContent = credit.textContent;
    picture.alt = art.alt;
    picture.src = art.currentSrc || art.src;
  }

  function open(frame, control) {
    opener = control;
    const film = frame.closest("[data-film]");
    group = film ? Array.from(film.querySelectorAll("figure[data-art]")) : [frame];
    show(group.indexOf(frame));
    viewer.showModal();
    close.focus();
  }

  for (const frame of frames) {
    const button = frame.querySelector(".image-opener");
    button.hidden = false;
    button.addEventListener("click", () => open(frame, button));
  }
  close.addEventListener("click", () => viewer.close());
  viewer.addEventListener("close", () => {
    gesture = null;
    opener?.focus({preventScroll:true});
  });
  viewer.addEventListener("click", (event) => {
    if (event.target === viewer) {
      const rect = viewer.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) viewer.close();
    }
    const step = event.target.closest("[data-viewer-step]");
    if (step) show(index + Number(step.dataset.viewerStep));
  });
  viewer.addEventListener("keydown", (event) => {
    if (event.altKey || event.metaKey || event.ctrlKey) return;
    const direction = {ArrowLeft:-1,ArrowRight:1}[event.key];
    if (!direction) return;
    event.preventDefault();
    show(index + direction);
  });
  sheet.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "touch" && event.isPrimary) gesture = {id:event.pointerId, x:event.clientX, y:event.clientY};
  });
  sheet.addEventListener("pointerup", (event) => {
    if (gesture?.id !== event.pointerId) return;
    const distance = event.clientX - gesture.x;
    const height = Math.abs(event.clientY - gesture.y);
    gesture = null;
    if (Math.abs(distance) > 46 && Math.abs(distance) > height * 1.5) show(index + (distance < 0 ? 1 : -1));
  });
  sheet.addEventListener("pointercancel", () => { gesture = null; });
})();
