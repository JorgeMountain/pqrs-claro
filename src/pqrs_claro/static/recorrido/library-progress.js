export function preparationSummary(status) {
  const count = key => Math.max(0, Number(status[key]) || 0);
  const ready = count('ready'), total = count('total');
  const remaining = count('queued') + count('preparing');
  let text = `Biblioteca: ${ready} de ${total} fuentes con texto preparado para buscar.`;
  if (remaining) text += ` ${remaining} en preparación. Puedes continuar mientras termina.`;
  if (count('unreadable')) text += ` ${count('unreadable')} sin texto utilizable; requieren extracción o revisión.`;
  if (count('error')) text += ` ${count('error')} con error de preparación. La búsqueda habitual sigue disponible.`;
  return text;
}

export async function watchPreparation(container, api, schedule = setTimeout) {
  if (!container?.isConnected) return;
  try {
    const status = await api('/api/library/preparation');
    if (!container.isConnected) return;
    container.textContent = preparationSummary(status);
    if (Number(status.queued) + Number(status.preparing) > 0) {
      schedule(() => watchPreparation(container, api, schedule), 4000);
    }
  } catch {
    if (container.isConnected) container.textContent = 'El estado de preparación no está disponible. Puedes continuar consultando las fuentes.';
  }
}
