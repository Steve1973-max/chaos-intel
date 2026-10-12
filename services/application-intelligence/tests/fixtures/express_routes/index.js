const express = require('express')
const app = express()
const router = express.Router()

app.get('/health', (req, res) => {})
router.post('/create', (req, res) => {})
router.get('/:id', (req, res) => {})

app.use('/api', router)
