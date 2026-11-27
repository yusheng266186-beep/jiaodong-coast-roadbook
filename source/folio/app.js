(() => {
  const root = document.documentElement;
  const data = JSON.parse(document.getElementById("itinerary-data").textContent);
  const route = data.routes[0];
  const storageKey = "travel-roadbook.v1." + data.trip.id;
  const mast = document.querySelector(".mast");
  const cover = document.querySelector(".cover-spread");
  const phoneLayout = matchMedia("(max-width: 700px)");
  const dayPages = Array.from(document.querySelectorAll("[data-day-page]"));
  const dayRail = document.querySelector(".day-nav");
  const dayTabs = Array.from(document.querySelectorAll("[data-day-select]"));
  const routeAtlas = document.getElementById("route-atlas");
  const atlasDetails = routeAtlas.closest("details");
  const atlasPages = Array.from(routeAtlas.querySelectorAll("[data-atlas-day]"));
  const atlasSteps = Array.from(routeAtlas.querySelectorAll("[data-atlas-step]"));
  const atlasPosition = document.getElementById("atlas-position");
  const pins = Array.from(routeAtlas.querySelectorAll("[data-stop]"));
  const placeEntries = new Map(
    Array.from(document.querySelectorAll("[data-place-entry]"), (entry) => [entry.dataset.placeEntry, entry])
  );
  const placeLookup = document.getElementById("place-lookup");
  const placeList = document.querySelector(".place-list");
  const placeDay = document.getElementById("place-day");
  const placeQuery = document.getElementById("place-query");
  const placeCount = document.getElementById("place-count");
  const placeReset = document.getElementById("place-reset");
  const placeEmpty = document.getElementById("place-empty");
  const placeViewer = document.getElementById("place-viewer");
  const placeViewerTitle = document.getElementById("place-viewer-title");
  const placeViewerPicture = document.getElementById("place-viewer-picture");
  const placeViewerInfo = document.getElementById("place-viewer-info");
  const viewerAddress = document.getElementById("place-viewer-address");
  const media = JSON.parse(document.getElementById("place-media-data").textContent);
  const artImages = new Map(Array.from(document.querySelectorAll("figure[data-art]"), figure =>
    [figure.dataset.art, figure.querySelector("img")]
  ));
  const placeFrame = placeViewerPicture.querySelector(".place-media-frame");
  const placeImage = placeFrame.querySelector("img");
  const photoPosition = document.getElementById("place-photo-position");
  const photoCaption = document.getElementById("place-photo-caption");
  const photoCredit = document.getElementById("place-photo-credit");
  const photoControls = placeViewerPicture.querySelector(".place-photo-controls");
  const filmstrip = photoControls.querySelector(".place-filmstrip");
  const photoSteps = [...photoControls.querySelectorAll("button")];
  const canViewPlace = typeof placeViewer.showModal === "function";
  const placeSequence = document.getElementById("place-sequence");
  const placeSequenceDays = Array.from(placeSequence.querySelectorAll("[data-place-route]"));
  const placeSequenceLink = placeSequence.querySelector("a.text-action");
  const placeSequenceTitle = document.getElementById("place-sequence-title");
  const placeSequenceNav = placeSequence.querySelector(".index-route-nav");
  const previousStop = placeSequenceNav.querySelector('[data-index-step="-1"]');
  const nextStop = placeSequenceNav.querySelector('[data-index-step="1"]');
  const placeBack = document.getElementById("place-back");
  const placeFilters = Array.from(document.querySelectorAll("[data-place-filter]"));
  const views = new Map(Array.from(document.querySelectorAll("[data-guide-view]"), view => [view.dataset.guideView, view]));
  const sceneryStops = new Map([...views].map(([id, view]) => [id, [...view.querySelectorAll("[data-scenery]")]]));
  const coastScenery = sceneryStage(document.getElementById("coast-scenery"));
  const placeScenery = sceneryStage(document.getElementById("place-scenery"));
  const navLinks = Array.from(document.querySelectorAll("[data-guide-tab]"));
  const returnAnchor = `field-${route.id}--event-${route.return_item_id}`;
  const scheduleID = (number) => `route-${route.id}--day-${number}`;
  const routeBack = document.getElementById("route-back");
  const sectionNames = {home:"封面", routes:"行程", places:"地点", food:"食单", "travel-tools":"行前准备", [returnAnchor]:"返程"};

  const lookupAnchor = "place-lookup";
  const entryFocus = new Map();
  let historyId = Date.now();
  let activeDay;
  let lookupDay = 1;
  let placeKind = "all";
  let activeView;
  let currentLocation;
  let scrollFrame;
  let readingFrame;
  let toastTimer;
  let gallery = [];
  let photoIndex = 0;
  let photoGesture;
  const copyTimers = new WeakMap();

  function keyFor(text) {
    return text.toLowerCase().replace(/[\s·・—–-]/gu, "");
  }

  function readStorage(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  }

  function writeStorage(key, value) {
    try { localStorage.setItem(key, value); } catch {}
  }

  function announce(message) {
    const status = document.getElementById("announcement");
    const toast = document.getElementById("toast");
    clearTimeout(toastTimer);
    status.textContent = "";
    requestAnimationFrame(() => { status.textContent = message; });
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 2000);
  }

  function dayAt(number) {
    return Math.min(route.days.length, Math.max(1, number || 1));
  }

  function visitIDs(day) {
    const planned = [];
    for (const item of day.items) {
      planned.push(...[item.from_id, item.place_id, item.to_id].filter(Boolean));
    }
    if (day.stay_id) planned.push(day.stay_id);
    const main = [...new Set(planned)];
    const alternate = [...new Set((day.alternatives || []).map((option) => option.place_id).filter(Boolean))]
      .filter((id) => !main.includes(id));
    return {main, alternate};
  }

  const visits = route.days.map((day, index) => {
    const {main, alternate} = visitIDs(day);
    for (const id of data.nearby_sights[String(index + 1)] || []) {
      if (!main.includes(id) && !alternate.includes(id)) alternate.push(id);
    }
    return {main, alternate};
  });
  const searchTerms = new Map(data.places.map((place) => [
    place.id, keyFor([place.name, place.area, place.address].filter(Boolean).join(" "))
  ]));
  const placeRegions = [...new Set(Array.from(placeEntries.values(), entry => entry.dataset.region))];

  function appendPlaceGroup(title, entries, expanded) {
    if (!entries.length) return;
    const group = document.createElement("details");
    group.className = "place-group";
    group.open = expanded;
    const summary = document.createElement("summary");
    const label = document.createElement("span");
    label.textContent = title;
    const count = document.createElement("span");
    count.textContent = entries.length + " 处";
    summary.append(label, count);
    const results = document.createElement("div");
    results.className = "place-group-entries";
    results.append(...entries);
    group.append(summary, results);
    placeList.append(group);
  }

  function syncSequenceNav() {
    const rail = placeSequenceDays[lookupDay - 1];
    const limit = rail.scrollWidth - rail.clientWidth;
    placeSequenceNav.hidden = limit <= 1;
    previousStop.disabled = rail.scrollLeft <= 1;
    nextStop.disabled = rail.scrollLeft >= limit - 1;
  }

  function renderPlaces() {
    const query = keyFor(placeQuery.value.trim());
    const byDate = placeDay.value !== "all";
    const filtered = Boolean(query) || byDate || placeKind !== "all";
    const {main, alternate} = visits[lookupDay - 1];
    const ids = query || !byDate ? [...placeEntries.keys()] : [...main, ...alternate];
    const matches = ids
      .filter(id => !query || searchTerms.get(id)?.includes(query))
      .map(id => placeEntries.get(id))
      .filter(entry => placeKind === "all" || entry.dataset.kind === placeKind);
    const visible = new Set(matches);
    placeList.replaceChildren();
    if (byDate && !query) {
      appendPlaceGroup("当天地点", matches.filter(entry => !alternate.includes(entry.dataset.placeEntry)), true);
      appendPlaceGroup("当天备选", matches.filter(entry => alternate.includes(entry.dataset.placeEntry)), false);
    } else {
      for (const region of placeRegions) {
        const entries = matches.filter(entry => entry.dataset.region === region);
        appendPlaceGroup(region, entries, Boolean(query) || placeKind !== "all");
      }
    }
    const parked = document.createElement("div");
    parked.hidden = true;
    for (const entry of placeEntries.values()) {
      if (!visible.has(entry)) parked.append(entry);
    }
    placeList.append(parked);
    placeSequence.hidden = !byDate || Boolean(query) || placeKind !== "all";
    for (const sequence of placeSequenceDays) sequence.hidden = Number(sequence.dataset.placeRoute) !== lookupDay;
    placeSequenceLink.href = "#" + scheduleID(lookupDay);
    placeSequenceTitle.textContent = `第 ${lookupDay} 天停靠顺序`;
    for (const button of [previousStop, nextStop]) button.setAttribute("aria-controls", placeSequenceDays[lookupDay - 1].id);
    syncSequenceNav();
    placeCount.textContent = matches.length + " 处地点";
    placeCount.parentElement.hidden = !filtered;
    placeEmpty.hidden = Boolean(matches.length);
  }

  function selectPlaceKind(kind) {
    placeKind = kind;
    for (const filter of placeFilters) {
      filter.setAttribute("aria-pressed", String(filter.dataset.placeFilter === kind));
    }
  }

  function photoSource(photo) {
    return photo.src || artImages.get(photo.art)?.src;
  }

  function sceneryStage(stage) {
    const layers = Array.from(stage.children);
    let front = 0;
    let scene;
    let request = 0;
    return async (name, getSource) => {
      if (name === scene) return;
      scene = name;
      const revision = ++request;
      const source = getSource?.();
      if (!source) {
        delete stage.dataset.scene;
        for (const layer of layers) {
          layer.removeAttribute("data-visible");
          layer.removeAttribute("src");
        }
        return;
      }
      const incoming = 1 - front;
      const image = layers[incoming];
      image.src = source;
      try { await image.decode(); } catch {
        if (revision === request) scene = undefined;
        return;
      }
      if (revision !== request) return;
      layers[front].removeAttribute("data-visible");
      image.setAttribute("data-visible", "");
      stage.dataset.scene = name;
      front = incoming;
    };
  }

  function showPlacePhoto(index) {
    photoIndex = Math.min(gallery.length - 1, Math.max(0, index));
    const photo = gallery[photoIndex];
    const source = photoSource(photo);
    placeImage.src = source;
    placeScenery(placeViewer.dataset.place + "-" + photoIndex, () => source);
    placeImage.alt = photo.caption;
    photoPosition.textContent = `第 ${photoIndex + 1} 张，共 ${gallery.length} 张`;
    photoCaption.textContent = photo.caption + " · 据实拍绘制";
    photoCredit.href = photo.reference;
    photoCredit.textContent = photo.credit || "查看实拍来源";
    photoSteps[0].disabled = photoIndex === 0;
    photoSteps[1].disabled = photoIndex === gallery.length - 1;
    for (const [index, button] of Array.from(filmstrip.children).entries()) {
      button.setAttribute("aria-pressed", String(index === photoIndex));
    }
    const entry = history.state?.guide;
    if (entry?.overlay && entry.photo !== photoIndex) {
      history.replaceState({...history.state, guide:{...entry, photo:photoIndex}}, "");
    }
  }

  function showPlace(card, imageIndex) {
    const id = card.id.slice(6);
    if (id !== placeViewer.dataset.place) placeScenery(null);
    placeViewer.dataset.place = id;
    placeViewer.dataset.kind = card.closest(".place-entry").dataset.kind;
    placeViewerTitle.textContent = card.querySelector("h4").textContent;
    placeViewerInfo.replaceChildren(card.querySelector(".place-facts").cloneNode(true));
    gallery = (media.places[id] || []).map(key => media.photos[key]).filter(photoSource);
    placeViewerPicture.hidden = gallery.length === 0;
    photoControls.hidden = gallery.length < 2;
    filmstrip.replaceChildren(...gallery.map((photo, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "place-photo-choice";
      button.setAttribute("aria-label", photo.caption);
      const image = document.createElement("img");
      image.src = photoSource(photo);
      image.alt = "";
      image.width = 52;
      image.height = 34;
      button.append(image);
      button.addEventListener("click", () => showPlacePhoto(index));
      return button;
    }));
    if (gallery.length) showPlacePhoto(imageIndex);
    else placeImage.removeAttribute("src");
    placeBack.disabled = false;
    if (!placeViewer.open) placeViewer.showModal();
    placeViewer.scrollTop = 0;
  }

  function revealDay() {
    if (!activeDay || dayRail.scrollWidth <= dayRail.clientWidth) return;
    const rail = dayRail.getBoundingClientRect();
    const tab = dayTabs[activeDay - 1].getBoundingClientRect();
    if (tab.left < rail.left - 1) dayRail.scrollLeft += tab.left - rail.left;
    if (tab.right > rail.right + 1) dayRail.scrollLeft += tab.right - rail.right;
  }

  function measureBars() {
    root.style.setProperty("--mast-height", mast.offsetHeight + "px");
    root.style.setProperty("--day-rail-height", dayRail.offsetHeight + "px");
    revealDay();
  }

  function setMapDay(number) {
    const day = dayAt(number);
    const atlasPage = atlasPages[day - 1];
    for (const page of atlasPages) page.hidden = page !== atlasPage;
    for (const pin of pins) {
      if (pin.dataset.stop === atlasPage.dataset.mapStop) pin.setAttribute("aria-current", "location");
      else pin.removeAttribute("aria-current");
    }
    routeAtlas.dataset.activeDay = atlasPage.dataset.atlasDay;
    atlasPosition.textContent = day + " / " + atlasPages.length;
    atlasSteps[0].disabled = day === 1;
    atlasSteps[1].disabled = day === atlasPages.length;
    scheduleReading();
  }

  function parseHash(hash) {
    const [fragment, query = ""] = hash.slice(1).split("?");
    const anchor = decodeURIComponent(fragment);
    if (anchor === "travel-log" || anchor === "exports") return {id:"travel-tools", day:null};
    if (anchor === returnAnchor) return {id:anchor, day:8};
    if (anchor.startsWith(`field-${route.id}--day-`)) return {id:anchor.replace("field-", "route-"), day:null};
    if (anchor.startsWith(`field-${route.id}--event-`)) return {id:anchor.slice(6), day:null};
    const storedDay = new URLSearchParams(query).get("day");
    const day = storedDay !== null && /^\d+$/.test(storedDay) ? dayAt(Number(storedDay) + 1) : null;
    return {id:anchor === "routes" && day ? scheduleID(day) : anchor, day};
  }

  function scheduleReading() {
    if (!readingFrame) readingFrame = requestAnimationFrame(trackReading);
  }

  function trackReading() {
    readingFrame = 0;
    const mastBottom = mast.getBoundingClientRect().bottom;
    root.classList.toggle("phone-cover", phoneLayout.matches && cover.getBoundingClientRect().bottom > mastBottom + 16);
    if (placeViewer.open) return;
    const line = mastBottom + 28;
    let section = "home";
    for (const [name, view] of views) {
      if (view.getBoundingClientRect().top <= line) section = name;
    }
    if (activeView !== section) {
      activeView = section;
      for (const link of navLinks) {
        if (link.dataset.guideTab === section) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      }
    }
    if (section === "home") {
      coastScenery(null);
      return;
    }
    const dayLine = section === "routes" ? line + dayRail.offsetHeight : line;
    const scene = sceneryStops.get(section).findLast(stop => stop.getBoundingClientRect().top <= dayLine);
    const atlas = section === "routes" && atlasDetails.open ? routeAtlas.getBoundingClientRect() : null;
    const mapArt = atlas && atlas.bottom > dayLine && atlas.top < innerHeight * .7
      ? atlasPages[Number(routeAtlas.dataset.activeDay) - 1].querySelector("figure[data-art]").dataset.art
      : null;
    const art = mapArt || scene?.dataset.scenery || views.get(section).dataset.scenery || "oldtown";
    coastScenery(art, () => artImages.get(art)?.src);
    if (section !== "routes") return;
    const current = dayPages.findLast(page => page.getBoundingClientRect().top <= dayLine);
    const day = Number(current?.dataset.dayPage || 1);
    if (activeDay === day) return;
    activeDay = day;
    for (const tab of dayTabs) {
      if (Number(tab.dataset.daySelect) === day) tab.setAttribute("aria-current", "date");
      else tab.removeAttribute("aria-current");
    }
    revealDay();
  }

  function reveal(target) {
    for (let node = target; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
  }

  function showRouteBack(entry, target) {
    const destination = target?.querySelector(":scope > .activity-body, :scope > .day-brief, :scope > .place-lookup-body");
    routeBack.hidden = !(entry?.from && destination);
    if (!routeBack.hidden) {
      routeBack.textContent = "返回" + sectionNames[entry.from];
      destination.prepend(routeBack);
    }
  }

  function restoreLookup(entry) {
    if (!entry?.lookup) return;
    const [date, query, kind, open] = entry.lookup;
    placeLookup.open = open;
    if (placeDay.value === date && placeQuery.value === query && placeKind === kind) return;
    placeDay.value = date;
    placeQuery.value = query;
    lookupDay = Number(date) || 1;
    selectPlaceKind(kind);
    renderPlaces();
  }

  function positionView({target, y, focus} = {}) {
    cancelAnimationFrame(scrollFrame);
    scrollFrame = requestAnimationFrame(() => {
      if (y !== undefined) window.scrollTo({top:y, behavior:"instant"});
      else if (target?.id === "top") window.scrollTo({top:0, behavior:"instant"});
      else target?.scrollIntoView({block:"start", behavior:"instant"});
      const node = focus || (target?.tagName === "DETAILS" ? target.firstElementChild : target?.querySelector(":scope > header h2") || target);
      if (node?.isConnected && node.getClientRects().length) {
        if (!node.matches("a,button,input,summary,[tabindex]")) node.tabIndex = -1;
        node.focus({preventScroll:true});
      }
      trackReading();
    });
  }

  function navigate({restore = false} = {}) {
    const entry = history.state?.guide;
    const key = location.hash + ":" + (entry?.id || "");
    if (currentLocation === key) return;
    currentLocation = key;
    cancelAnimationFrame(scrollFrame);
    let destination;
    try { destination = parseHash(location.hash); } catch { destination = {id:"top"}; }
    let target = document.getElementById(destination.id || "top");
    if (canViewPlace && target?.matches(".place-card")) {
      if (!placeViewer.open) {
        if (entry?.overlay && restore) {
          restoreLookup(entry);
          window.scrollTo({top:entry.originY, behavior:"instant"});
        }
        if (!entry?.overlay) {
          const backdrop = document.getElementById("view-" + target.id.slice(6)) || document.getElementById("places");
          backdrop.scrollIntoView({block:"start", behavior:"instant"});
        }
      }
      showPlace(target, entry?.photo ?? 0);
      return;
    }
    if (placeViewer.open) placeViewer.close();
    showRouteBack(entry, target);
    if (restore && entry?.y !== undefined) {
      restoreLookup(entry);
      positionView({y:entry.y, focus:entryFocus.get(entry.id)});
      return;
    }
    const atlasDay = target?.closest("[data-atlas-day]");
    if (atlasDay) setMapDay(Number(atlasDay.dataset.atlasDay));
    if (destination.day && ["places", "place-index", lookupAnchor].includes(target?.id)) {
      lookupDay = destination.day;
      placeDay.value = String(lookupDay);
      placeQuery.value = "";
      selectPlaceKind("all");
      renderPlaces();
      target = placeLookup;
    }
    if (target) {
      reveal(target);
      if (target?.closest("#place-lookup")) {
        requestAnimationFrame(syncSequenceNav);
      }
      if (location.hash || restore) positionView({target});
      else trackReading();
    }
  }

  function dismissPlace() {
    if (placeBack.disabled) return;
    placeBack.disabled = true;
    if (history.state?.guide?.overlay) {
      history.back();
    } else {
      const card = "view-" + parseHash(location.hash).id.slice(6);
      const fallback = document.getElementById(card) ? card : "place-index";
      history.replaceState({guide:{id:++historyId}}, "", "#" + fallback);
      navigate();
    }
  }

  function follow(control) {
    const href = control.dataset.placeLink || control.getAttribute("href");
    let id;
    try { ({id} = parseHash(href)); } catch { return false; }
    const target = document.getElementById(id);
    if (!target) return false;
    if (control.matches(".coast-pin") && target.dataset.atlasDay) {
      setMapDay(Number(target.dataset.atlasDay));
      return true;
    }
    const opensPlace = canViewPlace && target.matches(".place-card");
    if (location.hash === href && !opensPlace && !href.includes("?")) {
      reveal(target);
      positionView({target});
      return true;
    }
    const entry = history.state?.guide || {id:++historyId};
    entry.y = scrollY;
    entry.lookup = [placeDay.value, placeQuery.value, placeKind, placeLookup.open];
    if (placeViewer.open) entry.photo = photoIndex;
    else entryFocus.set(entry.id, control);
    history.replaceState({...history.state, guide:entry}, "");
    const next = {id:++historyId};
    if (opensPlace) {
      next.overlay = true;
      next.originY = scrollY;
      next.lookup = entry.lookup;
    } else if (!control.dataset.guideTab) {
      const section = target.closest("[data-guide-view]")?.dataset.guideView;
      if (section && section !== activeView) next.from = activeView;
    }
    history.pushState({guide:next}, "", href);
    navigate();
    return true;
  }

  root.classList.add("enhanced");
  history.scrollRestoration = "manual";
  routeBack.addEventListener("click", () => history.back());
  if (readStorage(storageKey + ".motion") === "reduced") root.dataset.motion = "reduced";
  measureBars();
  if (typeof ResizeObserver !== "undefined") {
    const bars = new ResizeObserver(measureBars);
    bars.observe(mast);
    bars.observe(dayRail);
  }
  setMapDay(1);
  atlasDetails.addEventListener("toggle", scheduleReading);
  for (const button of atlasSteps) {
    button.addEventListener("click", () => setMapDay(Number(routeAtlas.dataset.activeDay) + Number(button.dataset.atlasStep)));
  }
  renderPlaces();
  navigate();
  addEventListener("scroll", scheduleReading, {passive:true});
  addEventListener("resize", scheduleReading, {passive:true});
  window.addEventListener("popstate", () => navigate({restore:true}));
  window.addEventListener("hashchange", () => navigate());
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const control = event.target.closest(canViewPlace ? 'a[href^="#"], [data-place-link]' : 'a[href^="#"]');
    if (control && follow(control)) event.preventDefault();
  });

  for (const page of dayPages) {
    const button = page.querySelector("[data-day-expand]");
    const activities = Array.from(page.querySelectorAll(".activity"));
    function syncExpand() {
      const expanded = activities.every(activity => activity.open);
      button.setAttribute("aria-expanded", String(expanded));
      button.textContent = expanded ? "收起当天细节" : "展开当天细节";
    }
    page.addEventListener("toggle", (event) => {
      if (event.target.matches(".activity")) syncExpand();
    }, true);
    button.addEventListener("click", () => {
      const opening = activities.some(activity => !activity.open);
      for (const activity of activities) activity.open = opening;
      syncExpand();
    });
  }

  if (canViewPlace) {
    for (const entry of placeEntries.values()) entry.firstElementChild.setAttribute("aria-haspopup", "dialog");
    for (const link of document.querySelectorAll('a[href^="#place-"]')) {
      if (document.getElementById(parseHash(link.hash).id)?.matches(".place-card")) link.setAttribute("aria-haspopup", "dialog");
    }
  }
  placeBack.addEventListener("click", dismissPlace);
  viewerAddress.addEventListener("click", () => {
    const address = placeViewerInfo.querySelector(".place-address");
    const heading = address.querySelector("h3");
    heading.tabIndex = -1;
    heading.focus({preventScroll:true});
    address.scrollIntoView({block:"nearest", behavior:"instant"});
  });
  for (const button of photoSteps) {
    button.addEventListener("click", () => showPlacePhoto(photoIndex + Number(button.dataset.placePhotoStep)));
  }
  placeViewer.addEventListener("keydown", (event) => {
    if (gallery.length < 2 || event.altKey || event.metaKey || event.ctrlKey) return;
    const step = {ArrowLeft:-1, ArrowRight:1}[event.key];
    if (!step) return;
    event.preventDefault();
    showPlacePhoto(photoIndex + step);
  });
  placeFrame.addEventListener("pointerdown", (event) => {
    if (event.isPrimary && event.pointerType === "touch") photoGesture = {id:event.pointerId,x:event.clientX,y:event.clientY};
  });
  placeFrame.addEventListener("pointerup", (event) => {
    if (photoGesture?.id !== event.pointerId) return;
    const dx = event.clientX - photoGesture.x;
    const dy = event.clientY - photoGesture.y;
    if (gallery.length > 1 && Math.abs(dx) > 42 && Math.abs(dx) > Math.abs(dy) * 1.5) showPlacePhoto(photoIndex + (dx < 0 ? 1 : -1));
    photoGesture = null;
  });
  placeFrame.addEventListener("pointercancel", () => { photoGesture = null; });
  placeViewer.addEventListener("cancel", (event) => {
    event.preventDefault();
    dismissPlace();
  });
  placeViewer.addEventListener("click", (event) => {
    if (event.target !== placeViewer) return;
    const box = placeViewer.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dismissPlace();
  });
  placeLookup.addEventListener("toggle", syncSequenceNav);
  function applyPlaceDate() {
    const day = Number(placeDay.value);
    lookupDay = day || 1;
    const href = day ? `#place-lookup?day=${day - 1}` : "#place-lookup";
    history.replaceState(history.state, "", href);
    currentLocation = location.hash + ":" + (history.state?.guide?.id || "");
    renderPlaces();
  }
  placeDay.addEventListener("change", applyPlaceDate);
  placeQuery.addEventListener("input", renderPlaces);
  placeReset.addEventListener("click", () => {
    placeQuery.value = "";
    placeDay.value = "all";
    selectPlaceKind("all");
    applyPlaceDate();
    placeQuery.focus();
  });
  for (const filter of placeFilters) {
    filter.addEventListener("click", () => {
      selectPlaceKind(filter.dataset.placeFilter);
      renderPlaces();
    });
  }
  placeSequence.addEventListener("scroll", syncSequenceNav, {capture:true, passive:true});
  window.addEventListener("resize", syncSequenceNav);
  for (const button of [previousStop, nextStop]) {
    button.addEventListener("click", () => {
      const rail = placeSequenceDays[lookupDay - 1];
      rail.scrollBy({left:Number(button.dataset.indexStep) * rail.clientWidth * .78});
    });
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-copy]");
    if (!button) return;
    const label = button.querySelector("[data-copy-label]");
    const address = button.dataset.copy;
    try {
      await navigator.clipboard.writeText(address);
    } catch {
      const selection = document.createElement("textarea");
      selection.className = "sr-only";
      selection.value = address;
      const copyHost = button.closest("dialog[open]") || document.body;
      copyHost.append(selection);
      selection.select();
      const copied = document.execCommand("copy");
      selection.remove();
      button.focus({preventScroll:true});
      if (!copied) {
        announce("请选择地址文字后复制");
        return;
      }
    }
    clearTimeout(copyTimers.get(button));
    button.dataset.copied = "";
    label.textContent = "已复制";
    copyTimers.set(button, setTimeout(() => {
      delete button.dataset.copied;
      label.textContent = "复制地址";
    }, 2200));
    announce("已复制地址");
  });

  const items = Array.from(document.querySelectorAll("[data-check]"));
  const checkCount = document.getElementById("check-count");
  const progress = document.getElementById("prep-progress");
  const bookingSteps = Array.from(document.querySelectorAll("[data-booking-step]"));

  function records() {
    try {
      const snapshot = JSON.parse(readStorage(storageKey) || "{}");
      return snapshot && typeof snapshot === "object" && !Array.isArray(snapshot) ? snapshot : {};
    } catch {
      return {};
    }
  }

  function updateChecks() {
    const checked = items.filter(input => input.checked);
    checkCount.textContent = `${checked.length}/${items.length}`;
    progress.value = checked.length;
    for (const step of bookingSteps) {
      const total = Number(step.dataset.taskCount);
      const done = checked.filter(input => input.dataset.taskStep === step.dataset.bookingStep).length;
      const count = step.querySelector(".booking-count");
      count.textContent = `${done}/${total}`;
      count.setAttribute("aria-label", `已完成 ${done} 项，共 ${total} 项`);
      step.toggleAttribute("data-done", done === total);
    }
  }

  function loadChecks() {
    const {checks} = records();
    const checked = new Set(Array.isArray(checks) ? checks : []);
    for (const input of items) input.checked = checked.has(input.dataset.check);
    updateChecks();
  }

  document.querySelector(".checklist").addEventListener("change", ({target}) => {
    if (!target.matches("[data-check]")) return;
    const record = records();
    const checks = new Set(Array.isArray(record.checks) ? record.checks : []);
    if (target.checked) checks.add(target.dataset.check);
    else checks.delete(target.dataset.check);
    writeStorage(storageKey, JSON.stringify({tripId:data.trip.id,version:1,...record,checks:[...checks]}));
    updateChecks();
  });
  loadChecks();
  window.addEventListener("storage", (event) => { if (event.key === storageKey) loadChecks(); });

  const budget = document.querySelector(".budget");
  const budgetShares = Array.from(budget.querySelectorAll("[data-budget-share]"));
  const budgetTotals = new Map(Array.from(budget.querySelectorAll("[data-budget-total]"), row =>
    [row.dataset.budgetTotal, row.querySelector("dd")]
  ));
  const budgetKey = data.trip.id + ".budget-size";
  const format = new Intl.NumberFormat("zh-CN", {maximumFractionDigits:0});
  const yuan = (amount) => "¥" + format.format(amount);
  const yuanRange = (low, high) => yuan(low) + "–" + format.format(high);
  function updateBudget(number) {
    let low = 0;
    let high = 0;
    const groups = new Map(budgetShares.map(share => [share.dataset.budgetShare, 0]));
    for (const row of route.budget) {
      if (row.status === "pending") continue;
      const amount = row.basis === "per_person" ? number : (row.quantity ?? 1);
      const from = Number(row.amount) * amount;
      const to = Number(row.amount_max ?? row.amount) * amount;
      const cost = document.getElementById(`budget-${route.id}--${row.id}`);
      cost.querySelector("strong").textContent = yuanRange(from, to);
      const key = cost.dataset.budgetGroup;
      groups.set(key, groups.get(key) + to);
      low += from;
      high += to;
    }
    document.getElementById("budget-summary").textContent = yuanRange(low, high);
    document.getElementById("budget-average").textContent = yuanRange(low / number, high / number);
    for (const share of budgetShares) {
      const key = share.dataset.budgetShare;
      share.style.flexGrow = groups.get(key);
      budgetTotals.get(key).textContent = yuan(groups.get(key));
    }
  }
  const savedSize = Number(readStorage(budgetKey));
  if ([5,6].includes(savedSize)) {
    budget.querySelector(`input[value="${savedSize}"]`).checked = true;
    updateBudget(savedSize);
  }
  budget.addEventListener("change", ({target}) => {
    if (target.name !== "budget-people") return;
    updateBudget(Number(target.value));
    writeStorage(budgetKey, target.value);
  });

  const planner = document.getElementById("departure-form");
  const result = document.getElementById("departure-result");

  function clock(minutes) {
    const offset = Math.floor(minutes / 1440);
    const normalized = (minutes % 1440 + 1440) % 1440;
    const time = [Math.floor(normalized / 60), normalized % 60].map(number => String(number).padStart(2,"0")).join(":");
    return offset < 0 ? `提前 ${Math.abs(offset)} 天 ${time}` : time;
  }

  planner.addEventListener("submit", (event) => {
    event.preventDefault();
    const fields = new FormData(planner);
    const [hour, minute] = fields.get("departure").split(":").map(Number);
    const arrival = hour * 60 + minute - Number(fields.get("entry"));
    const boarding = arrival - Number(fields.get("ride"));
    const bags = boarding - Number(fields.get("bags"));
    const steps = [["开始退房取箱", bags], ["酒店出发", boarding], ["最晚到 T2", arrival]];
    result.replaceChildren(...steps.map(([label, minutes]) => {
      const row = document.createElement("span");
      const value = document.createElement("strong");
      value.textContent = clock(minutes);
      row.append(label, value);
      return row;
    }));
  });
  planner.addEventListener("reset", () => result.replaceChildren());

  let openedForPrint = [];
  window.addEventListener("beforeprint", () => {
    for (const details of document.querySelectorAll(".day-page details:not([open]), .preparation details:not([open]), .dish-details:not([open])")) {
      details.open = true;
      openedForPrint.push(details);
    }
  });
  window.addEventListener("afterprint", () => {
    for (const details of openedForPrint) details.open = false;
    openedForPrint = [];
  });

})();
