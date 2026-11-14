import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Studio } from './Studio'
import './styles.css'

const root = document.querySelector('#root')
if (!root) throw new Error('Contenitore dello studio mancante.')

createRoot(root).render(
  <StrictMode>
    <Studio />
  </StrictMode>,
)
