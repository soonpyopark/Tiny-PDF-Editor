import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

const EditorCommandsContext = createContext(null);

/** Shares the open editor's actions with the top menu. */
export function EditorCommandsProvider({ children }) {
  const handlersRef = useRef({});
  const [snapshot, setSnapshot] = useState({ ready: false, docOpen: false });

  const setHandlers = useCallback((handlers) => {
    handlersRef.current = handlers;
  }, []);

  const publish = useCallback((state) => {
    setSnapshot((prev) =>
      prev.ready === state.ready && prev.docOpen === state.docOpen ? prev : state,
    );
  }, []);

  const run = useCallback((name, ...args) => {
    const handler = handlersRef.current[name];
    if (typeof handler === 'function') return handler(...args);
    return undefined;
  }, []);

  return (
    <EditorCommandsContext.Provider value={{ setHandlers, publish, run, ...snapshot }}>
      {children}
    </EditorCommandsContext.Provider>
  );
}

export function useEditorCommands() {
  const context = useContext(EditorCommandsContext);
  if (!context) throw new Error('useEditorCommands must be used within EditorCommandsProvider');
  return context;
}

/** Keeps menu actions pointed at the latest editor handlers. */
export function useRegisterEditorCommands(handlers, state) {
  const { setHandlers, publish } = useEditorCommands();
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;
  setHandlers(handlersRef.current);

  const ready = Boolean(state.ready);
  const docOpen = Boolean(state.docOpen);
  useEffect(() => {
    publish({ ready, docOpen });
  }, [publish, ready, docOpen]);
}
