# Define the entry point script
$entryPointScript = @"
# Your entry point script code goes here
# This is the script that will be executed when the executable is run
"@

# Set the output path for the executable
$outputPath = "C:\path\to\output\egfet-experiment-controls.exe"

# Create the executable
Add-Type -TypeDefinition @"
using System;
using System.Management.Automation;

class Program
{
    static void Main(string[] args)
    {
        using (PowerShell ps = PowerShell.Create())
        {
            ps.AddScript(@"
$entryPointScript
"@
            );

            ps.Invoke();
        }
    }
}
"@

# Save the executable to the output path
$executableCode = @"
using System;
using System.IO;
using System.Reflection;

class Program
{
    static void Main(string[] args)
    {
        string modulePath = Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "egfet-experiment-controls.psm1");
        string scriptPath = Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "entrypoint.ps1");

        File.WriteAllText(scriptPath, @"
$entryPointScript
"@
        );

        using (PowerShell ps = PowerShell.Create())
        {
            ps.AddScript(@"
Import-Module $modulePath
. $scriptPath
"@
            );

            ps.Invoke();
        }

        File.Delete(scriptPath);
    }
}
"@

Add-Type -TypeDefinition $executableCode -OutputType ConsoleApplication -OutputAssembly $outputPath