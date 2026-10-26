import 'dotenv/config';
import express from 'express';
import routes from './routes.js';
import conn from './db.js';

const app = express();
app.use(express.json());

async function startServer() {
    try {
        await conn;
        
        app.use(routes);

        app.listen(process.env.PORT || 555, () => {
            console.log('Server running on http://localhost:555');
        });
    } catch (e) {
        console.error('Connection failed: ', e.message);
        process.exitCode = 1;
    }
}

startServer();