export async function getDb() {
  const url = process.env.DATABASE_URL
  if (!url) throw new Error('DATABASE_URL not set')
  const { neon } = await import('@neondatabase/serverless')
  return neon(url)
}
