# Guion del PPT · Demo BCAC POC (versión inicial)

> Las capturas las genero yo arrancando la app (http://127.0.0.1:5000, usuario `admin` / `gencat`).

## 0. Datos generales

- **Título del PPT:**  "BCAC · Gestión documental con gobernanza"
- **Audiencia:**  cliente Generalitat  equipo interno de negocio
- **Idioma del PPT:** catalán
- **Plantilla o formato corporativo Ayesa:** Formato corporativo segun css de proyecto 
- **Duración / nº aproximado de diapositivas:** 30 min

## 1. contenidos a utilizar en la demo

Disponibles hoy en `uploads/` y `normativa/`. Indica cuál va en cada caso.

| Ciclo | Tipo de contenido | Archivo a subir | Metadatos (departamento, tipología, canal, idioma, taxonomía…) |
|---|---|---|---|
| 1 | BASE_FM |  `uploads/BASE_Families_nombroses.pdf` | "Familles_nombrosa" , "Descripció del tràmit o servei" , "Drets Socials i Inclusio", "Societat i ciutadania > Families > Titol Família Nombrosa" |
| 2 | ADAPTAT_FM | `uploads/ADAPTAT_260724_Vigent_PRESTACIONS_FAMILIES_v310.pdf`| "Adaptat" , "Catala" , "Descripció del tràmit o servei" , "Familles_nombroses(v1)" , "WEB"|
| 3 | BASE_INCOHERENTE_FM |  `uploads/BASE_INCOHERENTE_Families_nombroses.pdf` | "Familles_nombrosa" , "Descripció del tràmit o servei" , "Drets Socials i Inclusio", "Societat i ciutadania > Families > Titol Família Nombrosa" |
| Normativa | — | `normativa/Decret de Protecció a les Famílies Nombroses (1).pdf` | — |



## 2. Diapositivas

### 2.1 Portada
- Base Coneixement Atenció Ciutadana ​POC​ 

### 2.2 Indice

### 2.3 Interficie - Una pestanya per cada perfil​
- Demostració de la interfície i dels dos cicles de vida dels documents​
- pestañas de ciclo contenido BASE
- Pestañas ciclo contenido Adaptado
- Pestañas comunes 

### 2.4 Els dos cicles de vida​
- ciclo de vida contenido base 
- ciclo de vida contenido adaptado


### 2.5  Contenido Base 
- Una slide por cada una de las lineas que siguen. EN cada linea te indico el rol y lo que quiero que aparezca.  
- Editor departamental- mostrar boton de subida
- Editor departamental- subida de contenido. sube BASE_FM, todas las opciones deben de ser visibles.
- Vision del dashboard de editor con el contenido subido BASE_FM. Solo ese contenido. 
- Referente departamental, analisis con IA. 
- Referente departamental vision de resultados de analisis sobre pdf del contenido BASE_INCOHERENTE_FM
- Referente departamental aprobacion del contenido BASE_FM. Solo debe de verse este contenido en la lista.
- Validador Finalista , analisis normativo del contenido BASE_FM
- Validador finalista , vision de resultados de analisis normativo sobre pdf con contenido  BASE_FM
- Validador Finalista , aprobacion del contenido  BASE_FM
- Gestor conocimiento cord, Deteccion de duplicidades  mostrar resultados analizando BASE_FM cuando no hay contenidos publicados. 
- Gestor conocimiento cord. Mostrar cuando se detectan duplicidades. Ver cuando se sube BASE_Incoherente_FM una vez tenemos BASE_FM en publicado. 
- Gestor Conocimiento Cord- Publicacion de contenido BASE_FM
- Rechazo  desde cualquier fase de validación: vuelve al Editor Departamental.
- Nueva versión de un contenido publicado, ver que la version publicada queda publicada.
- Nueva version , ver qeu el contenido aparece en el editor con una version inclrementada y la posibilidad de editarlo.
- Nueva version, mostrar que cuiando se completa el cilo de validaciones queda publicada la nueva version y la version precedente pasa a retirada.
- Retirada: El contenido deja de estar visible para los agentes pero sigue en la BCAC.


### 2.6 Contenido Adaptat
- Una slide por cada una de las lineas que siguen. EN cada linea te indico el rol y lo que quiero que aparezca.  
- Editor canal, boton de subida.
- Editor canal, formulario de subida de documenbto que se vea entero para subir contenido ADAPTAT_FM 
- Editor canal, vision del contenido subido y aprovacion
- Gestor conocimiento canal comprobaciones IA
- Gestor conocimiento canal , mostrar resultado comprobacion fidelidad IA en PDF
- Gestor conocimiento canal rechazo con motivo.
- Editor canal , vision de contenido rechazado y edicion 
- Gestor de conocimiento canal , publicacion. 
- Gestor de conocimiento canal nueva version , ver que el contenido publicado queda publicado y ver que la version sucesora va al editor.  
- Editor , vuelta para nueva version. 
- Nueva versión de un contenido publicado, ver que la version publicada queda publicada.
- Nueva version , ver qeu el contenido aparece en el editor con una version inclrementada y la posibilidad de editarlo.
- Nueva version, mostrar que cuiando se completa el cilo de validaciones queda publicada la nueva version y ver que la version antigua pasa a retirados
- Retirada: Mostrar que un continido publicado puede ser retirado


## 3. Notas y preferencias de estilo

- El mismo estilo del CSS del proyecto y con el logo de la genaralitat en el encabezado 
- Cada vez que mostremos la aplicacion debe de mostrarse el la pantalla completa de la aplicacion con todo lo que quieres mostrar visible. No la recortes para centrate solo en lo que quieres mostrar 
- En las capturas de la aplicacion en cada caso en el dashboars solo debe de verse el documnento que se indica. 
