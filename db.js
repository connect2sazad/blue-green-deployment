import { MongoClient } from 'mongodb';

const client = new MongoClient(process.env.MONGODB_URI);

async function connect() {

    await client.connect();

    const db = client.db('multi-container-service-deployment');
    const todos = db.collection('todos');

    console.log('MongoDB atlas connected!');

    return todos;
}

const conn = connect();

export default conn;
