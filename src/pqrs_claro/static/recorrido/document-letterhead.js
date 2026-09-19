// Perfil visual del membrete original conservado en data/templates.
// Se aplica solo a esta versión: otra plantilla mantiene la vista genérica.
const templateHash='a7a81df06ceee7bb7b00443c03ce1293861dffa00b05d2e1d02b1a9bcd029120';
export const hasUdeaLayout=letterhead=>letterhead?.sha256===templateHash;
export function addUdeaLetterhead(sheet){
  sheet.classList.add('udea-letterhead');
  const header=document.createElement('div');header.className='oficio-institutional-header';
  const logo=document.createElement('img');logo.src='/letterhead-udea.png';
  logo.alt='Universidad de Antioquia · Facultad de Ingeniería';header.append(logo);
  const footer=document.createElement('footer');footer.className='oficio-institutional-footer';
  const lines=[
    'Decanatura',
    'Ciudad Universitaria: Calle 67 No. 53-108, bloque 18, oficina 119 • Recepción de correspondencia: Calle 70 No 52-21',
    'Teléfono: 219 55 00 • Fax: 263 82 82 • Nit: 890.980.040-8 • Apartado: 1226',
    'http://ingenieria.udea.edu.co • Medellín, Colombia',
  ];
  for(const text of lines){const line=document.createElement('div');line.textContent=text;footer.append(line);}
  sheet.append(header,footer);
}
