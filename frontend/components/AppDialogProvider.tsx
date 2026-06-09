import {
  createContext,
  FormEvent,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useId,
  useState,
} from 'react';

type DialogKind = 'alert' | 'confirm' | 'prompt';

interface DialogOptions {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}

interface PromptOptions extends DialogOptions {
  defaultValue?: string;
  placeholder?: string;
  multiline?: boolean;
}

interface DialogState extends PromptOptions {
  kind: DialogKind;
  resolve: (value: boolean | string | null | undefined) => void;
}

interface AppDialogApi {
  alert: (options: string | DialogOptions) => Promise<void>;
  confirm: (options: string | DialogOptions) => Promise<boolean>;
  prompt: (options: string | PromptOptions) => Promise<string | null>;
}

const AppDialogContext = createContext<AppDialogApi | null>(null);

const normalizeOptions = (options: string | DialogOptions): DialogOptions =>
  typeof options === 'string' ? { message: options } : options;

export function AppDialogProvider({ children }: { children: ReactNode }) {
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [inputValue, setInputValue] = useState('');
  const titleId = useId();
  const messageId = useId();

  const openDialog = useCallback((request: Omit<DialogState, 'resolve'>) => {
    return new Promise<boolean | string | null | undefined>((resolve) => {
      setInputValue(request.defaultValue || '');
      setDialog({ ...request, resolve });
    });
  }, []);

  const alert = useCallback<AppDialogApi['alert']>(
    async (options) => {
      const normalized = normalizeOptions(options);
      await openDialog({
        kind: 'alert',
        title: normalized.title || '提示',
        message: normalized.message,
        confirmText: normalized.confirmText || '知道了',
      });
    },
    [openDialog]
  );

  const confirm = useCallback<AppDialogApi['confirm']>(
    async (options) => {
      const normalized = normalizeOptions(options);
      const result = await openDialog({
        kind: 'confirm',
        title: normalized.title || '请确认',
        message: normalized.message,
        confirmText: normalized.confirmText || '确认',
        cancelText: normalized.cancelText || '取消',
        danger: normalized.danger,
      });
      return result === true;
    },
    [openDialog]
  );

  const prompt = useCallback<AppDialogApi['prompt']>(
    async (options) => {
      const normalized = typeof options === 'string' ? { message: options } : options;
      const result = await openDialog({
        kind: 'prompt',
        title: normalized.title || '请输入',
        message: normalized.message,
        confirmText: normalized.confirmText || '提交',
        cancelText: normalized.cancelText || '取消',
        defaultValue: normalized.defaultValue || '',
        placeholder: normalized.placeholder,
        multiline: normalized.multiline,
        danger: normalized.danger,
      });
      return typeof result === 'string' ? result : null;
    },
    [openDialog]
  );

  const closeDialog = useCallback((value: boolean | string | null | undefined) => {
    setDialog((current) => {
      current?.resolve(value);
      return null;
    });
  }, []);

  useEffect(() => {
    if (!dialog) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (dialog.kind === 'alert') {
        closeDialog(undefined);
      } else if (dialog.kind === 'confirm') {
        closeDialog(false);
      } else {
        closeDialog(null);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [closeDialog, dialog]);

  const handleDismiss = () => {
    if (!dialog) return;
    if (dialog.kind === 'alert') {
      closeDialog(undefined);
    } else if (dialog.kind === 'confirm') {
      closeDialog(false);
    } else {
      closeDialog(null);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!dialog) return;
    if (dialog.kind === 'prompt') {
      closeDialog(inputValue);
    } else if (dialog.kind === 'confirm') {
      closeDialog(true);
    } else {
      closeDialog(undefined);
    }
  };

  return (
    <AppDialogContext.Provider value={{ alert, confirm, prompt }}>
      {children}
      {dialog && (
        <div className="modal-mask app-dialog-mask" onClick={handleDismiss}>
          <form
            className={`modal-card app-dialog ${dialog.danger ? 'app-dialog--danger' : ''}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={messageId}
            onClick={(event) => event.stopPropagation()}
            onSubmit={handleSubmit}
          >
            <button className="modal-close app-dialog__close" type="button" aria-label="关闭" onClick={handleDismiss}>
              ×
            </button>
            <div className="app-dialog__body">
              <h2 id={titleId}>{dialog.title}</h2>
              <p id={messageId}>{dialog.message}</p>
              {dialog.kind === 'prompt' &&
                (dialog.multiline ? (
                  <textarea
                    className="input app-dialog__textarea"
                    value={inputValue}
                    placeholder={dialog.placeholder}
                    autoFocus
                    onChange={(event) => setInputValue(event.target.value)}
                  />
                ) : (
                  <input
                    className="input"
                    value={inputValue}
                    placeholder={dialog.placeholder}
                    autoFocus
                    onChange={(event) => setInputValue(event.target.value)}
                  />
                ))}
            </div>
            <div className="app-dialog__actions">
              {dialog.kind !== 'alert' && (
                <button className="button ghost" type="button" onClick={handleDismiss}>
                  {dialog.cancelText || '取消'}
                </button>
              )}
              <button
                className={`button ${dialog.danger ? 'danger' : 'primary'}`}
                type="submit"
                autoFocus={dialog.kind !== 'prompt'}
              >
                {dialog.confirmText || '确认'}
              </button>
            </div>
          </form>
        </div>
      )}
    </AppDialogContext.Provider>
  );
}

export function useAppDialog() {
  const context = useContext(AppDialogContext);
  if (!context) {
    throw new Error('useAppDialog must be used within AppDialogProvider');
  }
  return context;
}
