import { toast } from "sonner";

export function showSuccess(message: string) {
  toast.success(message);
}

export function showError(message: string, description?: string) {
  toast.error(message, { description });
}

export async function confirmAction(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    toast(message, {
      action: {
        label: "Confirm",
        onClick: () => resolve(true),
      },
      duration: 10000,
      onAutoClose: () => resolve(false),
      onDismiss: () => resolve(false),
    });
  });
}
