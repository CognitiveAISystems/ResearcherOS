(async () => {
  const send = (type, fields = {}) => window.parent.postMessage({ type, ...fields }, "*");

  try {
    window.EXCALIDRAW_ASSET_PATH = "https://cdn.jsdelivr.net/npm/@excalidraw/excalidraw@0.18.0/dist/prod/";
    const [{ createElement }, { createRoot }, { Excalidraw, serializeAsJSON }] = await Promise.all([
      import("https://esm.sh/react@19.0.0"),
      import("https://esm.sh/react-dom@19.0.0/client?deps=react@19.0.0"),
      import("https://esm.sh/@excalidraw/excalidraw@0.18.0?deps=react@19.0.0,react-dom@19.0.0&bundle"),
    ]);

    let editor;
    let version;
    let savedVersion;
    let dirty = false;

    function updateDirty(force = false) {
      const next = version !== savedVersion;
      if (!force && dirty === next) return;
      dirty = next;
      send("canvas-dirty", { dirty });
    }

    window.addEventListener("message", ({ source, data }) => {
      if (source !== window.parent) return;
      if (data?.type === "canvas-init" && !editor) {
        createRoot(document.getElementById("editor")).render(createElement(Excalidraw, {
          initialData: { ...data.scene, scrollToContent: true },
          langCode: "ru-RU",
          theme: data.theme === "light" ? "light" : "dark",
          excalidrawAPI: (api) => { editor = api; },
          onChange: (elements, appState) => {
            if (appState.isLoading) return;
            version = JSON.stringify([appState.viewBackgroundColor, elements.map((element) => [
              element.id, element.version, element.versionNonce,
            ])]);
            if (savedVersion === undefined) {
              savedVersion = version;
              send("canvas-ready");
            }
            updateDirty();
          },
        }));
      } else if (data?.type === "canvas-save" && editor) {
        send("canvas-snapshot", {
          scene: serializeAsJSON(editor.getSceneElements(), editor.getAppState(), editor.getFiles(), "local"),
          version,
        });
      } else if (data?.type === "canvas-saved") {
        savedVersion = data.version;
        updateDirty(true);
      }
    });
    send("canvas-load");
  } catch (error) {
    console.error(error);
    send("canvas-error");
  }
})();
